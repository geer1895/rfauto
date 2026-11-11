"""ODB++ 目录解析内核+服务+CLI 单测（aurora_q 席位 Q-X68，2026-11-08）。

夹具纪律（任务书口径）：tmp_path 内**程序化构建 ODB++ 目录树**（块式
matrix 文本+steps/pcb 两层 features 小文件+cadnet 2 net 多点+symbols
2 条）+ 真实 KiCad 10 导出样例
（tests/fixtures/external/kicad10_microwave_odb，git 跟踪 52 文件）
只读消费。零 run 湖写入（#144），零网络零真机。

**任务书 netlist 形态勘误（规范钉，Q-X59 勘误家法）**：任务书口径
「UNIT MM / NET 段 / ( pin refdes pin_num ) 连接对 / % 子段」与公开
规范（odbplusplus.com 8.1U3 p138-144）与 KiCad 实导出均不符——真实
cadnet/netlist= ``H optimize <y|n> [staggered <y|n>]`` 头行 +
``$<serial> <net_name>`` 名段 + 数字点行；「NET/SNT/pin 连接对」在
eda/data（NET/SNT TOP comp_num+toep_num）与 components（TOP net_num+
pin_num）——本测试按规范与 fixture 双证钉定（本仓测试文件正文零 ``%``
裸字面、help 卫生 #305 同源）。

覆盖面（任务书 ≥55 条）：matrix 块式/子集行式双形态（大写↔小写映射
表驱动）、ROW 排序/缺名/未知语句 warning、符号名分类（µm/mil→mm 精确
换算 Fraction 表驱动已知量）、features 行分类统计、cadnet 头行/名段/
点行全字段（side/w-h/epoint/exp/旗标/staggered/键值/-1 tooling）、
eda/data 记录面（NET/SNT/FID/PKG/PIN/PRP）、components（CMP/TOP/PRP/
BOM）、目录树（tmp 树+真实 fixture 只读）、inventory 悬空/空 net 双
清单（宁多报）、stack 对齐缺失/多余、fail-soft、信封契约、CLI --json
双路径+help 真构建（#305）+计数链字面钉+cli.main 零导入钉。
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains.odbpp import odbpp_app
from rfauto.core.odbpp_parser import (
    PARSER_SCHEMA_VERSION,
    OdbppParseError,
    classify_symbol_name,
    odbpp_layer_stack_summary,
    odbpp_net_inventory,
    parse_odb_cadnet,
    parse_odb_components,
    parse_odb_dir,
    parse_odb_eda_data,
    parse_odb_features,
    parse_odb_info,
    parse_odb_matrix,
    parse_odb_stephdr,
    parse_odb_symbol_table,
)
from rfauto.service import odbpp_service

runner = CliRunner()

#: 真实 KiCad 10 导出样例（git 跟踪；只读消费）。
REAL_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "external" / \
    "kicad10_microwave_odb"

# ══════════════════ tmp_path 程序化夹具（目录树工厂）══════════════════

MATRIX_STEPS = """\
STEP {
    COL=1
    NAME=PCB
}

LAYER {
    ROW=1
    CONTEXT=BOARD
    TYPE=SIGNAL
    NAME=F.CU
    OLD_NAME=
    POLARITY=POSITIVE
    COLOR=0
}

LAYER {
    ROW=2
    CONTEXT=BOARD
    TYPE=DIELECTRIC
    NAME=DIELECTRIC_1
    DIELECTRIC_TYPE=CORE
    POLARITY=POSITIVE
    COLOR=0
}

LAYER {
    ROW=3
    CONTEXT=BOARD
    TYPE=SIGNAL
    NAME=B.CU
    OLD_NAME=
    POLARITY=POSITIVE
    COLOR=0
}

LAYER {
    ROW=4
    CONTEXT=MISC
    TYPE=DOCUMENT
    NAME=EDGE.CUTS
    POLARITY=POSITIVE
    COLOR=0
}

LAYER {
    ROW=5
    CONTEXT=BOARD
    TYPE=COMPONENT
    NAME=COMP_+_TOP
    POLARITY=POSITIVE
    COLOR=0
}
"""

FEATURES_F_CU = """\
UNITS=MM
#
#Num Features
#
F 6
#
#Feature symbol names
#
$0 rect612.14x612.14
$1 r304.80
#
#Feature attribute names
#
@0 .pad_usage
#
#Feature attribute text strings
#
&0 toeprint
#
#Layer features
#
P 10.0 20.0 0 P 0 0;0=0
P 30.0 20.0 0 P 0 0
L 10.0 20.0 30.0 20.0 1 P 0
L 30.0 20.0 40.0 20.0 1 P 0
S P 0
OB 0.0 0.0 I
OS 0.0 0.0
OS 0.0 10.0
OS 10.0 10.0
OS 10.0 0.0
OS 0.0 0.0
OE
SE
"""

FEATURES_B_CU = """\
UNITS=MM
#
#Num Features
#
F 1
#
#Layer features
#
L 5.0 5.0 15.0 5.0 0 P 0
"""

CADNET_MAIN = """\
H optimize n staggered n
$0 GND
$1 VCC
$2 NC_NET
#
#Netlist points
#
0 0 10.0 20.0 T 0.61 0.61 e c
0 0 30.0 20.0 T 0.61 0.61 e c t
1 0 5.0 5.0 B m e e v
-1 0.5 99.0 99.0 T e e
"""

EDA_DATA = """\
HDR KiCad EDA 10.0.6
UNITS=MM
LYR f.cu

#
#Feature attribute names
#

#
#Feature attribute text strings
#
NET GND
SNT TOP T 0 0
FID C 0 0
FID C 0 2
NET VCC
SNT TRC
FID C 0 3
PKG POLY 2.0 -1.0 -1.0 1.0 1.0;
CT
OB -1.0 -1.0 I
OE
CE
PIN 1 S 0.5 0.0 0 E S
PIN 2 S -0.5 0.0 0 E S
PRP Value 'R'
"""

COMPONENTS = """\
UNITS=MM

#
#Feature attribute names
#
@0 .comp_mount_type

#
#Feature attribute text strings
#
# CMP 0
CMP 0 10.0 -5.0 0 N R1 RES
PRP Value '10K'
TOP 1 10.0 20.0 0.0 N 0 0 1
TOP 2 30.0 20.0 0.0 N 0 1 2

# BOM DATA
CPN RC0603
MPN RC0603FR-0710KL
"""

STEPCONTEXT = "UNITS=MM\nX_DATUM=0\nY_DATUM=0\n"

INFO = """\
JOB_NAME=job
UNITS=MM
ODB_VERSION_MAJOR=8
ODB_VERSION_MINOR=1
ODB_SOURCE=KiCad EDA
SAVE_APP=KiCad EDA 10.0.6
"""

def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path

def build_odb_tree(root: Path, *, full: bool = True) -> Path:
    """程序化构建 ODB++ 目录树（matrix/step/layers/cadnet/eda/symbols）。"""
    _write(root, "matrix/matrix", MATRIX_STEPS)
    _write(root, "misc/info", INFO)
    _write(root, "steps/pcb/stephdr", STEPCONTEXT)
    _write(root, "steps/pcb/layers/f.cu/features", FEATURES_F_CU)
    _write(root, "steps/pcb/layers/f.cu/attrlist", ".layer_dielectric=0.03\n")
    _write(root, "steps/pcb/layers/b.cu/features", FEATURES_B_CU)
    _write(root, "steps/pcb/layers/edge.cuts/features",
           "UNITS=MM\n#\n#Layer features\n#\nL 0 0 10 0 0 P 0\n")
    _write(root, "steps/pcb/layers/dielectric_1/features",
           "UNITS=MM\n#\n#Num Features\n#\nF 0\n")
    if full:
        _write(root, "steps/pcb/netlists/cadnet/netlist", CADNET_MAIN)
        _write(root, "steps/pcb/eda/data", EDA_DATA)
        _write(root, "steps/pcb/layers/comp_+_top/components", COMPONENTS)
    _write(root, "symbols/rect600x400/features",
           "UNITS=MM\n#\n#Layer features\n#\nP 0 0 0 P 0\n")
    _write(root, "symbols/rect600x400/attrlist", "hole_type=plated\n")
    return root

# ══════════════════════════ matrix 解析 ══════════════════════════

class TestMatrix:
    def test_kind_steps(self):
        doc = parse_odb_matrix(MATRIX_STEPS)
        assert doc["kind"] == "steps"
        assert doc["schema"] == f"odbpp/{PARSER_SCHEMA_VERSION}"

    def test_layers_sorted_by_row(self):
        doc = parse_odb_matrix(MATRIX_STEPS)
        assert [entry["row"] for entry in doc["layers"]] == [1, 2, 3, 4, 5]

    def test_layer_fields(self):
        doc = parse_odb_matrix(MATRIX_STEPS)
        first = doc["layers"][0]
        assert first["name"] == "F.CU"
        assert first["type"] == "SIGNAL"
        assert first["context"] == "BOARD"
        assert first["polarity"] == "POSITIVE"

    def test_dielectric_type(self):
        doc = parse_odb_matrix(MATRIX_STEPS)
        assert doc["layers"][1]["dielectric_type"] == "CORE"

    def test_layer_dir_map_upper_lower(self):
        # 表驱动：大写 NAME ↔ 小写目录名（KiCad 口径/AGENTS 速查同账）
        doc = parse_odb_matrix(MATRIX_STEPS)
        assert doc["layer_dir_map"]["f.cu"] == "F.CU"
        assert doc["layer_dir_map"]["b.cu"] == "B.CU"
        assert doc["layer_dir_map"]["edge.cuts"] == "EDGE.CUTS"
        assert doc["layer_dir_map"]["comp_+_top"] == "COMP_+_TOP"

    def test_steps_list(self):
        doc = parse_odb_matrix(MATRIX_STEPS)
        assert doc["steps"] == ["PCB"]

    def test_row_gap_order_insensitive(self):
        # ROW 顺序不敏感可跳号（规范 p67）——乱序输入按 ROW 排
        text = ("LAYER {\nROW=5\nNAME=L5\n}\nLAYER {\nROW=2\nNAME=L2\n}\n")
        doc = parse_odb_matrix(text)
        assert [e["name"] for e in doc["layers"]] == ["L2", "L5"]

    def test_row_non_integer_warns_sorts_last(self):
        text = "LAYER {\nROW=x\nNAME=A\n}\nLAYER {\nROW=1\nNAME=B\n}\n"
        doc = parse_odb_matrix(text)
        assert doc["layers"][0]["name"] == "B"
        assert doc["layers"][1]["name"] == "A"
        assert doc["layers"][1]["row"] is None
        assert any("ROW 非整数" in w for w in doc["warnings"])

    def test_layer_missing_name_warns(self):
        doc = parse_odb_matrix("LAYER {\nROW=1\n}\n")
        assert doc["layers"] == []
        assert any("缺 NAME" in w for w in doc["warnings"])

    def test_unknown_statement_in_block_warns(self):
        doc = parse_odb_matrix("LAYER {\nBOGUS free text\nNAME=A\n}\n")
        assert any("未识别语句" in w for w in doc["warnings"])

    def test_raw_unit(self):
        doc = parse_odb_matrix("UNITS=MM\nMATRIX\n0 0 TOP top SIGNAL\n")
        assert doc["raw_unit"] == "MM"

    def test_subset_kind(self):
        # 子集行式（layout_interchange.export_odbpp 仓内口径）双形态同读取器
        doc = parse_odb_matrix("MATRIX\n0 0 TOP top SIGNAL\n1 0 BOT bot SIGNAL\n")
        assert doc["kind"] == "subset"
        assert doc["layer_dir_map"] == {"top": "TOP", "bot": "BOT"}
        assert [e["name"] for e in doc["layers"]] == ["TOP", "BOT"]
        assert doc["layers"][0]["type"] == "SIGNAL"

    def test_empty_doc_warns(self):
        doc = parse_odb_matrix("# empty\n")
        assert doc["layers"] == []
        assert any("无 STEP/LAYER 块" in w for w in doc["warnings"])

    def test_warnings_deduped(self):
        text = "LAYER {\nBOGUS a\n}\nLAYER {\nBOGUS b\n}\n"
        doc = parse_odb_matrix(text)
        # 两条不同语句各自入账；同文不重复
        assert len([w for w in doc["warnings"] if "未识别语句" in w]) == 2

# ══════════════════════════ 符号名分类 ══════════════════════════

class TestSymbolClassify:
    def test_round_um(self):
        # 表驱动已知量：r304.80（µm）→ 0.3048mm 直径（KiCad fixture 实证）
        info = classify_symbol_name("r304.80", "M")
        assert info["standard"] is True
        assert info["shape"] == "round"
        assert info["width_mm"] == pytest.approx(0.3048)
        assert info["height_mm"] == pytest.approx(0.3048)

    def test_rect_um(self):
        info = classify_symbol_name("rect612.14x612.14", "M")
        assert info["shape"] == "rectangle"
        assert info["width_mm"] == pytest.approx(0.61214)
        assert info["height_mm"] == pytest.approx(0.61214)

    def test_rect_mil(self):
        # 表驱动已知量：rect20x60（mil）→ 0.508×1.524mm（20×25.4/1000）
        info = classify_symbol_name("rect20x60", "I")
        assert info["width_mm"] == pytest.approx(0.508)
        assert info["height_mm"] == pytest.approx(1.524)

    def test_no_unit_hint_sizes_none_params_kept(self):
        info = classify_symbol_name("r100")
        assert info["params"] == [Fraction(100)]
        assert info["width_mm"] is None
        assert info["standard"] is True

    def test_non_standard_name(self):
        info = classify_symbol_name("punch_target", "M")
        assert info["standard"] is False
        assert info["shape"] is None

    def test_unknown_prefix(self):
        info = classify_symbol_name("foo123", "M")
        assert info["standard"] is False

    def test_moire_params(self):
        info = classify_symbol_name("moire50x10x3x5x10")
        assert info["standard"] is True
        assert info["shape"] == "moire"
        assert len(info["params"]) == 5

    def test_null_symbol(self):
        info = classify_symbol_name("null")
        assert info["standard"] is True
        assert info["shape"] == "null"

    def test_bfr_round(self):
        assert classify_symbol_name("bfr118.11", "M")["shape"] == "round"

class TestSymbolTable:
    def test_rows_parsed(self):
        doc = parse_odb_symbol_table("$0 rect612.14x612.14\n$1 r304.80 M\n")
        assert [s["index"] for s in doc["symbols"]] == [0, 1]
        assert doc["symbols"][1]["unit_hint"] == "M"
        assert doc["symbols"][1]["width_mm"] == pytest.approx(0.3048)

    def test_malformed_row_warns(self):
        doc = parse_odb_symbol_table("$bad\n")
        assert doc["symbols"] == []
        assert any("形态异常" in w for w in doc["warnings"])

# ══════════════════════════ features 行分类统计 ══════════════════════════

class TestFeatures:
    def test_units_and_count(self):
        doc = parse_odb_features(FEATURES_F_CU)
        assert doc["units"] == "MM"
        assert doc["declared_count"] == 6

    def test_symbols_section(self):
        doc = parse_odb_features(FEATURES_F_CU)
        assert [s["name"] for s in doc["symbols"]] == [
            "rect612.14x612.14", "r304.80"]

    def test_attr_tables(self):
        doc = parse_odb_features(FEATURES_F_CU)
        assert doc["attr_names"] == {"0": ".pad_usage"}
        assert doc["attr_texts"] == {"0": "toeprint"}

    def test_record_token_counts(self):
        doc = parse_odb_features(FEATURES_F_CU)
        assert doc["records"] == {
            "P": 2, "L": 2, "S": 1, "OB": 1, "OS": 5, "OE": 1, "SE": 1}

    def test_coordinate_rows_and_pad_refs(self):
        doc = parse_odb_features(FEATURES_F_CU)
        # L2+P2+OB1+OS5 = 10 坐标行；P 2
        assert doc["coordinate_rows"] == 10
        assert doc["pad_refs"] == 2

    def test_attr_assigns(self):
        doc = parse_odb_features(FEATURES_F_CU)
        assert doc["attr_assigns"] == 1  # P ... ;0=0

    def test_unknown_token_warns_counted(self):
        doc = parse_odb_features(
            "UNITS=MM\n#\n#Layer features\n#\nX 1 2 3\nL 0 0 1 0 0 P 0\n")
        assert doc["records"].get("X") == 1
        assert any("未知特征记录 token" in w for w in doc["warnings"])

    def test_nonstandard_units_warns(self):
        doc = parse_odb_features("UNITS=MIL\n")
        assert doc["units"] == "MIL"
        assert any("非规范枚举" in w for w in doc["warnings"])

    def test_records_before_features_section_not_counted(self):
        # 段序守卫：#Layer features 之前的未识别行不入 records
        doc = parse_odb_features("UNITS=MM\nBOGUS 1 2\n#\n#Layer features\n#\n"
                                 "L 0 0 1 0 0 P 0\n")
        assert doc["records"] == {"L": 1}
        assert doc["before_features"] == 1
        assert any("特征区前未识别" in w for w in doc["warnings"])

    def test_empty_features(self):
        doc = parse_odb_features("UNITS=MM\n#\n#Num Features\n#\nF 0\n")
        assert doc["declared_count"] == 0
        assert doc["records"] == {}

# ══════════════════════════ cadnet 网表 ══════════════════════════

class TestCadnet:
    def test_header(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        assert doc["header"] == {"optimize": "n", "staggered": "n"}

    def test_nets_order_by_serial(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        assert doc["nets"] == ["GND", "VCC", "NC_NET"]

    def test_point_full_fields(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        p0 = doc["net_points"][0]
        assert p0["net"] == "GND"
        assert (p0["x"], p0["y"]) == (10.0, 20.0)
        assert p0["side"] == "T"
        assert (p0["w"], p0["h"]) == (0.61, 0.61)
        assert p0["epoint"] == "e"
        assert p0["exp"] == "c"

    def test_wh_only_when_radius_zero(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        assert doc["net_points"][0]["radius"] == 0.0
        assert doc["net_points"][0]["w"] == 0.61

    def test_tooling_hole_neg_one(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        hole = doc["net_points"][3]
        assert hole["net_num"] == -1
        assert hole["tooling_hole"] is True
        assert hole["net"] is None
        assert doc["stats"]["n_tooling_holes"] == 1

    def test_flags(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        assert "t" in doc["net_points"][1]["flags"]
        assert "v" in doc["net_points"][2]["flags"]
        assert doc["stats"]["n_test_points"] == 1
        assert doc["stats"]["n_via_points"] == 1

    def test_side_hist(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        assert doc["stats"]["sides_hist"] == {"T": 3, "B": 1}

    def test_undefined_net_num_warns(self):
        doc = parse_odb_cadnet("H optimize n\n$0 GND\n5 0 0 0 T e e\n")
        assert doc["net_points"][0]["net"] is None
        assert any("未定义 net_num 5" in w for w in doc["warnings"])

    def test_missing_units_warns(self):
        doc = parse_odb_cadnet("H optimize n\n$0 GND\n0 0 0 0 T e e\n")
        assert doc["units"] is None
        assert any("无 UNITS" in w for w in doc["warnings"])

    def test_units_line_tolerated(self):
        doc = parse_odb_cadnet("UNITS=MM\nH optimize n\n$0 GND\n0 0 0 0 T e e\n")
        assert doc["units"] == "MM"

    def test_missing_header_warns(self):
        doc = parse_odb_cadnet("$0 GND\n0 0 0 0 T e e\n")
        assert doc["header"]["optimize"] is None
        assert any("先于 H 头行" in w for w in doc["warnings"])

    def test_old_style_side_suffix_warns(self):
        doc = parse_odb_cadnet("H optimize n\n$0 GND\n0 0 0 0 I2 e e\n")
        assert doc["net_points"][0]["side"] == "I"
        assert any("旧式层号后缀" in w for w in doc["warnings"])

    def test_staggered_and_params(self):
        line = ("0 0 1.0 2.0 B m e e staggered 0.1 0.2 0.3 by=b "
                "arsize_top=0.01 ld=111\n")
        doc = parse_odb_cadnet("H optimize n\n$0 GND\n" + line)
        pt = doc["net_points"][0]
        assert pt["staggered"] == [0.1, 0.2, 0.3]
        assert pt["params"]["by"] == "b"
        assert pt["params"]["arsize_top"] == "0.01"
        assert pt["params"]["ld"] == "111"

    def test_unknown_key_param_warns_registered(self):
        doc = parse_odb_cadnet(
            "H optimize n\n$0 GND\n0 0 0 0 T e e mystery=7\n")
        assert doc["net_points"][0]["params"]["mystery"] == "7"
        assert any("未知键值参数" in w for w in doc["warnings"])

    def test_malformed_net_row_warns(self):
        doc = parse_odb_cadnet("H optimize n\n$bad\n")
        assert doc["nets"] == []
        assert any("net 名行形态异常" in w for w in doc["warnings"])

    def test_stats(self):
        doc = parse_odb_cadnet(CADNET_MAIN)
        assert doc["stats"]["n_nets"] == 3
        assert doc["stats"]["n_points"] == 4

# ══════════════════════════ eda/data 与 components ══════════════════════════

class TestEdaData:
    def test_hdr_and_lyr(self):
        doc = parse_odb_eda_data(EDA_DATA)
        assert doc["hdr"] == "KiCad EDA 10.0.6"
        assert doc["layers"] == ["f.cu"]

    def test_net_order(self):
        doc = parse_odb_eda_data(EDA_DATA)
        assert doc["net_names"] == ["GND", "VCC"]

    def test_snt_top_fields(self):
        doc = parse_odb_eda_data(EDA_DATA)
        snt = doc["nets"][0]["subnets"][0]
        assert snt["kind"] == "TOP"
        assert snt["side"] == "T"
        assert snt["comp_num"] == 0
        assert snt["toep_num"] == 0

    def test_fid_attached_to_snt(self):
        doc = parse_odb_eda_data(EDA_DATA)
        snt = doc["nets"][0]["subnets"][0]
        assert snt["fids"] == [
            {"type": "C", "lyr_num": 0, "f_num": 0},
            {"type": "C", "lyr_num": 0, "f_num": 2},
        ]

    def test_pkg_pin_counts(self):
        doc = parse_odb_eda_data(EDA_DATA)
        assert doc["stats"]["n_packages"] == 1
        assert doc["stats"]["n_pins"] == 2
        assert doc["packages"][0]["name"] == "POLY"
        assert doc["packages"][0]["pitch"] == 2.0

    def test_prp_grouped_to_pkg(self):
        doc = parse_odb_eda_data(EDA_DATA)
        assert doc["packages"][0]["properties"] == {"Value": "'R'"}

    def test_outline_counted_only(self):
        doc = parse_odb_eda_data(EDA_DATA)
        assert doc["records"]["OB"] == 1
        assert doc["records"]["CE"] == 1

    def test_unknown_record_warns(self):
        doc = parse_odb_eda_data("HDR x\nBOGUS 1\n")
        assert any("未识别记录" in w for w in doc["warnings"])

class TestComponents:
    def test_cmp_fields(self):
        doc = parse_odb_components(COMPONENTS)
        cmp0 = doc["components"][0]
        assert cmp0["pkg_ref"] == 0
        assert (cmp0["x"], cmp0["y"]) == (10.0, -5.0)
        assert cmp0["mirrored"] is False
        assert cmp0["comp_name"] == "R1"
        assert cmp0["part_name"] == "RES"

    def test_top_pins(self):
        doc = parse_odb_components(COMPONENTS)
        pins = doc["components"][0]["pins"]
        assert [p["pin_num"] for p in pins] == [1, 2]
        assert [p["net_num"] for p in pins] == [0, 0]
        assert [p["toeprint"] for p in pins] == ["1", "2"]

    def test_prp_properties(self):
        doc = parse_odb_components(COMPONENTS)
        assert doc["components"][0]["properties"] == {"Value": "'10K'"}

    def test_bom_section(self):
        doc = parse_odb_components(COMPONENTS)
        assert doc["bom"] == {"CPN": "RC0603",
                              "MPN": "RC0603FR-0710KL"}

    def test_cmp_short_fields_warns(self):
        doc = parse_odb_components("CMP 0 1.0 2.0\n")
        assert doc["components"][0]["comp_name"] is None
        assert any("字段不足" in w for w in doc["warnings"])

    def test_attr_lookup_lines_skipped(self):
        doc = parse_odb_components(
            "@0 .x\n&0 v\nCMP 0 1 2 0 N A B\n")
        assert doc["components"][0]["comp_name"] == "A"
        assert doc["warnings"] == []

# ══════════════════════════ stephdr / info ══════════════════════════

class TestStephdrInfo:
    def test_stephdr(self):
        doc = parse_odb_stephdr(STEPCONTEXT)
        assert doc["units"] == "MM"
        assert doc["fields"]["X_DATUM"] == "0"

    def test_stephdr_missing_units_warns(self):
        doc = parse_odb_stephdr("X_DATUM=1\n")
        assert doc["units"] is None
        assert any("无 UNITS" in w for w in doc["warnings"])

    def test_info(self):
        doc = parse_odb_info(INFO)
        assert doc["units"] == "MM"
        assert doc["job_name"] == "job"
        assert doc["odb_version"] == "8.1"
        assert doc["odb_source"] == "KiCad EDA"

# ══════════════════════════ 目录树 ══════════════════════════

class TestDirTree:
    def test_full_tree(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        doc = parse_odb_dir(root)
        assert doc["schema"] == f"odbpp/{PARSER_SCHEMA_VERSION}"
        assert doc["model_units"] == "MM"
        assert doc["matrix"]["steps"] == ["PCB"]
        assert doc["stats"]["n_layers_declared"] == 5
        assert doc["stats"]["n_layers_on_disk"] == 5

    def test_step_contents(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        doc = parse_odb_dir(root)
        step = doc["steps"][0]
        assert step["name"] == "pcb"
        assert step["stephdr"]["units"] == "MM"
        assert step["dir_layers"] == ["b.cu", "comp_+_top", "dielectric_1",
                                      "edge.cuts", "f.cu"]
        assert step["cadnet"]["nets"] == ["GND", "VCC", "NC_NET"]
        assert step["eda_data"]["net_names"] == ["GND", "VCC"]
        assert step["stack_summary"]["aligned"] is True

    def test_layer_contents(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        doc = parse_odb_dir(root)
        fcu = next(lay for lay in doc["steps"][0]["layers"] if lay["name"] == "f.cu")
        assert fcu["matrix_name"] == "F.CU"
        assert fcu["features"]["pad_refs"] == 2
        assert fcu["attrlist"] == {".layer_dielectric": "0.03"}

    def test_symbols_dir(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        doc = parse_odb_dir(root)
        assert len(doc["symbols"]) == 1
        sym = doc["symbols"][0]
        assert sym["name"] == "rect600x400"
        assert sym["classify"]["shape"] == "rectangle"
        assert sym["features"]["pad_refs"] == 1

    def test_root_missing_raises(self, tmp_path: Path):
        with pytest.raises(OdbppParseError, match="目录不存在"):
            parse_odb_dir(tmp_path / "gone")

    def test_missing_matrix_raises(self, tmp_path: Path):
        root = tmp_path / "job"
        root.mkdir()
        (root / "steps").mkdir()
        with pytest.raises(OdbppParseError, match="缺 matrix"):
            parse_odb_dir(root)

    def test_extra_layer_dir_warns(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        _write(root, "steps/pcb/layers/rogue/features",
               "UNITS=MM\n#\n#Layer features\n#\nL 0 0 1 0 0 P 0\n")
        doc = parse_odb_dir(root)
        assert doc["steps"][0]["stack_summary"]["extra"] == ["rogue"]
        assert any("多余层" in w for w in doc["warnings"])

    def test_missing_layer_dir_warns(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        import shutil
        shutil.rmtree(root / "steps" / "pcb" / "layers" / "b.cu")
        doc = parse_odb_dir(root)
        assert doc["steps"][0]["stack_summary"]["missing"] == ["B.CU"]
        assert doc["steps"][0]["stack_summary"]["aligned"] is False

    def test_unreadable_file_fail_soft(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        (root / "steps" / "pcb" / "layers" / "f.cu" / "features").unlink()
        doc = parse_odb_dir(root)
        fcu = next(lay for lay in doc["steps"][0]["layers"] if lay["name"] == "f.cu")
        assert fcu["features"] is None  # 不可读如实 None（fail-soft 不判错）

    def test_subset_tree(self, tmp_path: Path):
        # 子集行式 matrix（layout_interchange.export_odbpp 口径）目录树
        root = tmp_path / "subset"
        _write(root, "matrix/matrix",
               "MATRIX\nUNITS=MM\n0 0 TOP top SIGNAL\n")
        _write(root, "steps/pcb/layers/top/features",
               "UNITS=MM\n#\n#Layer features\n#\nL 0 0 1 0 0 P 0\n")
        doc = parse_odb_dir(root)
        assert doc["matrix"]["kind"] == "subset"
        assert doc["stats"]["n_layers_declared"] == 1

# ══════════════════════════ 真实 KiCad fixture（只读）══════════════════

@pytest.mark.skipif(not REAL_FIXTURE.is_dir(), reason="真实 fixture 不在树")
class TestRealKiCadFixture:
    def test_matrix_shape(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        assert doc["matrix"]["kind"] == "steps"
        assert doc["matrix"]["steps"] == ["PCB"]
        assert len(doc["matrix"]["layers"]) == 22
        assert doc["matrix"]["layer_dir_map"]["f.cu"] == "F.CU"

    def test_stack_aligned(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        assert doc["steps"][0]["stack_summary"]["aligned"] is True

    def test_model_units(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        assert doc["model_units"] == "MM"
        assert doc["info"]["save_app"].startswith("KiCad EDA 10")

    def test_features_stats(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        assert doc["stats"]["n_features_records"] == 6731
        assert doc["stats"]["n_pad_refs"] == 8

    def test_fcu_features(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        fcu = next(lay for lay in doc["steps"][0]["layers"]
                   if lay["name"] == "f.cu")
        assert fcu["features"]["records"]["OS"] == 3256
        assert fcu["features"]["pad_refs"] == 8
        widths = {(s["name"],
                   round(s["width_mm"], 9) if s["width_mm"] is not None else None)
                  for s in fcu["features"]["symbols"]}
        # KiCad 实测无显式后缀 → 按文件 UNITS=MM 千分位（µm）缺省换算
        # （规范 p175；layout_interchange KiCad 实证同账）
        assert ("r304.80", round(0.3048, 9)) in widths
        assert ("rect612.14x612.14", round(0.61214, 9)) in widths
        assert ("rect1224.28x1224.28", round(1.22428, 9)) in widths

    def test_cadnet(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        cad = doc["steps"][0]["cadnet"]
        assert cad["header"] == {"optimize": "n", "staggered": "n"}
        assert cad["nets"] == ["$NONE$"]
        assert cad["stats"]["n_points"] == 8
        assert cad["stats"]["sides_hist"] == {"T": 8}
        assert cad["units"] is None  # KiCad 实测缺 UNITS 行（规范必需）

    def test_eda_data(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        eda = doc["steps"][0]["eda_data"]
        assert eda["hdr"] == "KiCad EDA 10.0.6"
        assert eda["net_names"] == ["$NONE$"]
        assert eda["stats"]["n_packages"] == 3
        assert eda["stats"]["n_pins"] == 6

    def test_components(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        comps = next(lay for lay in doc["steps"][0]["layers"]
                     if lay["name"] == "comp_+_top")["components"]
        assert comps["stats"]["n_components"] == 4
        assert comps["stats"]["n_pins"] == 8
        assert comps["components"][0]["comp_name"] == "POLY"

    def test_inventory(self):
        doc = parse_odb_dir(REAL_FIXTURE)
        inv = odbpp_net_inventory(doc["steps"][0])
        assert inv["stats"]["n_nets"] == 1
        assert inv["stats"]["n_pin_refs"] == 16  # eda SNT 8 + components TOP 8
        assert inv["empty_nets"] == []
        assert inv["dangling_pads"] == []

    def test_no_spurious_warnings(self):
        # 19 条结构化 warning 全数消化后=1（cadnet 缺 UNITS 如实登记）
        doc = parse_odb_dir(REAL_FIXTURE)
        assert len(doc["warnings"]) == 1
        assert "无 UNITS" in doc["warnings"][0]

# ══════════════════════════ inventory 与 stack ══════════════════════════

class TestInventory:
    def _step_doc(self, tmp_path: Path) -> dict:
        root = build_odb_tree(tmp_path / "job")
        return parse_odb_dir(root)["steps"][0]

    def test_nets_merge_cadnet_eda(self, tmp_path: Path):
        inv = odbpp_net_inventory(self._step_doc(tmp_path))
        assert set(inv["nets"]) == {"GND", "VCC", "NC_NET"}
        assert inv["nets"]["GND"]["points"] == 2
        assert inv["nets"]["VCC"]["points"] == 1

    def test_pins_via_net_num_join(self, tmp_path: Path):
        # components TOP net_num=0 → eda net 序[0]=GND（规范 p160）
        inv = odbpp_net_inventory(self._step_doc(tmp_path))
        assert ("R1", "1") in inv["nets"]["GND"]["pins"]
        assert ("R1", "2") in inv["nets"]["GND"]["pins"]

    def test_empty_net_constructed(self, tmp_path: Path):
        # NC_NET：cadnet 有名零点、eda 无该 net → 空 net 清单（宁多报）
        inv = odbpp_net_inventory(self._step_doc(tmp_path))
        assert inv["empty_nets"] == ["NC_NET"]

    def test_dangling_pads_no_net_evidence(self, tmp_path: Path):
        # full=False：step 无 cadnet/eda → 零 net 证据 → f.cu（pad_refs=2）
        # 整层入悬空清单（计数级宁多报；b.cu/edge.cuts 零 P 记录不入）
        root = build_odb_tree(tmp_path / "job", full=False)
        doc = parse_odb_dir(root)
        inv = odbpp_net_inventory(doc["steps"][0])
        assert inv["dangling_pads"] == [{"layer": "f.cu", "pad_refs": 2}]
        assert inv["stats"]["n_dangling_layers"] == 1

    def test_no_dangling_when_net_evidence(self, tmp_path: Path):
        inv = odbpp_net_inventory(self._step_doc(tmp_path))
        assert inv["dangling_pads"] == []

    def test_inventory_stats(self, tmp_path: Path):
        inv = odbpp_net_inventory(self._step_doc(tmp_path))
        assert inv["stats"]["n_nets"] == 3
        assert inv["stats"]["n_empty_nets"] == 1
        # GND: eda SNT TOP (CMP0,0) 1 + components TOP net_num=0 (R1,1)/(R1,2) 2
        assert inv["stats"]["n_pin_refs"] == 3

class TestStackSummary:
    def _matrix(self) -> dict:
        return parse_odb_matrix(MATRIX_STEPS)

    def test_aligned(self):
        summary = odbpp_layer_stack_summary(
            self._matrix(),
            ["f.cu", "dielectric_1", "b.cu", "edge.cuts", "comp_+_top"])
        assert summary["aligned"] is True
        assert summary["missing"] == []
        assert summary["extra"] == []

    def test_missing_and_extra(self):
        summary = odbpp_layer_stack_summary(
            self._matrix(), ["f.cu", "rogue"])
        assert summary["missing"] == ["B.CU", "COMP_+_TOP", "DIELECTRIC_1",
                                      "EDGE.CUTS"]
        assert summary["extra"] == ["rogue"]
        assert summary["aligned"] is False
        assert any("缺失" in w for w in summary["warnings"])
        assert any("多余" in w for w in summary["warnings"])

    def test_case_insensitive_match(self):
        summary = odbpp_layer_stack_summary(self._matrix(), ["F.CU"])
        assert summary["missing"] == ["B.CU", "COMP_+_TOP", "DIELECTRIC_1",
                                      "EDGE.CUTS"]
        assert summary["extra"] == []

# ══════════════════════════ 服务信封 ══════════════════════════

class TestService:
    def test_parse_dir_ok_envelope(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        result = odbpp_service.parse_odbpp_dir(root)
        assert result["ok"] is True
        assert result["kind"] == "odbpp"
        assert str(result["root"]).endswith("job")
        assert result["matrix"]["steps"] == ["PCB"]

    def test_parse_dir_missing_error_envelope(self, tmp_path: Path):
        result = odbpp_service.parse_odbpp_dir(tmp_path / "nope")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert all(isinstance(e, str) for e in result["errors"])
        assert "解析失败" in result["errors"][0]

    def test_parse_dir_missing_matrix_error_envelope(self, tmp_path: Path):
        root = tmp_path / "job"
        root.mkdir()
        result = odbpp_service.parse_odbpp_dir(root)
        assert result["ok"] is False
        assert "缺 matrix" in result["errors"][0]

    def test_report_envelope(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        result = odbpp_service.odbpp_report(root)
        assert result["ok"] is True
        assert result["kind"] == "odbpp_report"
        assert result["matrix_kind"] == "steps"
        assert result["n_layers_declared"] == 5
        assert result["n_layers_on_disk"] == 5
        assert result["model_units"] == "MM"

    def test_report_step_aggregates(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        result = odbpp_service.odbpp_report(root)
        step = result["steps"][0]
        assert step["name"] == "pcb"
        assert step["stack_aligned"] is True
        assert step["n_pad_refs"] == 2  # f.cu P 2（b.cu/edge.cuts 零 P 记录）
        assert step["n_nets"] == 3
        assert step["n_net_points"] == 4
        assert step["empty_nets"] == ["NC_NET"]

    def test_report_empty_net_aggregate(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        result = odbpp_service.odbpp_report(root)
        assert result["empty_nets"] == ["NC_NET"]
        assert result["n_empty_nets"] == 1

    def test_report_dangling_aggregate(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job", full=False)
        result = odbpp_service.odbpp_report(root)
        assert result["n_dangling_pads"] == 1
        assert result["dangling_pads"][0]["layer"] == "f.cu"

    def test_report_propagates_error(self, tmp_path: Path):
        result = odbpp_service.odbpp_report(tmp_path / "nope")
        assert result["ok"] is False

    def test_report_real_fixture(self):
        if not REAL_FIXTURE.is_dir():
            pytest.skip("真实 fixture 不在树")
        result = odbpp_service.odbpp_report(REAL_FIXTURE)
        assert result["ok"] is True
        assert result["steps"][0]["stack_aligned"] is True
        assert result["stats"]["n_features_records"] == 6731

# ══════════════════════════ CLI 一叶 ══════════════════════════

def _wired_app() -> typer.Typer:
    """合流接线形态镜像（接线两步处方的第 1 步；零共享 app 触碰）。"""
    root = typer.Typer()
    root.add_typer(odbpp_app, name="odbpp")
    return root

def _invoke(*args: object):
    argv: list[str] = []
    for arg in args:
        if isinstance(arg, (list, tuple)):
            argv.extend(str(item) for item in arg)
        else:
            argv.append(str(arg))
    return runner.invoke(_wired_app(), ["odbpp", *argv],
                         catch_exceptions=False)

class TestCli:
    def test_report_json_envelope(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        res = _invoke("report", ["--dir", str(root), "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["kind"] == "odbpp_report"
        assert envelope["empty_nets"] == ["NC_NET"]
        assert envelope["steps"][0]["stack_aligned"] is True

    def test_report_json_failure_envelope(self, tmp_path: Path):
        res = _invoke("report", ["--dir", str(tmp_path / "nope"), "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_report_human_output(self, tmp_path: Path):
        root = build_odb_tree(tmp_path / "job")
        res = _invoke("report", ["--dir", str(root)])
        assert res.exit_code == 0, res.output
        assert "ODB++ 报告" in res.output
        assert "layers_declared=5" in res.output
        assert "NC_NET" in res.output  # 空 net 清单
        assert "对齐" in res.output

    def test_report_human_failure_exit_1(self, tmp_path: Path):
        res = _invoke("report", ["--dir", str(tmp_path / "nope")])
        assert res.exit_code == 1
        assert "ODB++ 报告失败" in res.output

    def test_missing_dir_flag_fails(self):
        res = _invoke("report")
        assert res.exit_code != 0

    def test_help_builds_no_bare_percent(self):
        # #305 家法：--help 真构建 + 零裸 %
        for leaf in (["report", "--help"], ["--help"]):
            res = _invoke(*leaf)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_cli_leaf_literal_pin(self):
        # 计数链钉：odbpp 域恰 1 叶（report）、带 --json（新叶无 --json 即红）
        source = Path(odbpp_service.__file__).parent.parent.joinpath(
            "cli", "domains", "odbpp.py").read_text(encoding="utf-8")
        assert source.count('@odbpp_app.command("report")') == 1
        assert source.count("@odbpp_app.command(") == 1
        assert source.count("json_output: bool = typer.Option") == 1
        assert '--json", "-j"' in source
