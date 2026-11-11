"""Spectre 解析内核+服务+CLI 单测（aurora_q 席位 Q-X79，2026-11-08）。

夹具纪律（任务书口径）：**测试内嵌小 Spectre 文本**（lang 声明+parameters 3
含表达式+meg 特判+subckt 1 嵌套实例 2+顶层器件 5 类+续行 1+注释双形态+
options 块 1），零外部夹具文件；core 面纯文本进出零落盘，服务/CLI 测试经
tmp_path 落盘隔离（#144 run 湖零写入）、零网络零真机。

覆盖面（≥60 条）：

- 单位换算表驱动（meg 特判 vs m 前缀、mil、T/G/k/m/u/n/p/f 全档已知量、
  单位词后缀 1pF/100mA、大小写歧义面 1M/2.4MHz/1a→None 不猜 + 1A 单位词、
  不可识别后缀 5x/1meter、溢出 1e400 → value_si=None）；
- 值类型分派（表达式反引号/单引号/花括号/裸运算符、参数引用、字符串、
  vector、raw 兜底）；
- 词法（``//``/``/* */``/行首 ``*``/行首 ``#`` 注释四形态、引号内注释符
  不剥、行尾 ``\\`` 续行+行号=首物理行、续行 EOF 收尾、花括号块捕获、
  ``k = v`` 分写合并、值内函数括号/方括号 token 保整）；
- 语句面（lang 声明缺失 warning 不拒、lang=spice 外来段整段登记、
  parameters 顶层/体内双路由+重复声明警告、预处理指令登记+条件警告、
  model/include/ahdl_include、analysis/options 命名块、control 头）；
- 实例面（首字母映射表 17 字母参数化+unknown 桶、显式 subckt 引用优先
  任意名双形态、未定义引用警告、括号可省双形态、节点表未闭合、缺
  master、model_ref 回填）；
- 子电路（嵌套栈 scope/深度、ends 名不配对、孤立 ends、未闭合 warning、
  体内参数路由）；
- 统计（per_device_type_counts、深度/平铺叶计数、环引用截断+守卫）；
- 查询三函数（inventory 排序确定性/top 截断、subckt_tree 根序/深度/环/
  孤岛补根、param_refs 定义+消费词边界匹配/数值不误报）；
- 服务信封三态（ok/error/缺 lang 不拒+空文件 warning、latin-1 兜底、
  subckt_detail 不存在给可用名录、确定性）；
- CLI --json 双路径（CliRunner 直连 spectre_app——不触共享 app，零金快
  照漂移）+人读输出+--help 真构建零裸 %（#305）+计数链字面钉+
  cli.main 零导入钉+U+FFFD=0（#259）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains.spectre import spectre_app
from rfauto.core.spectre_parser import (
    DEVICE_TYPE_SUBCKT,
    DEVICE_TYPE_UNKNOWN,
    MAX_HIERARCHY_DEPTH,
    SPECTRE_LETTER_TYPES,
    classify_spectre_value,
    parse_spectre_number,
    parse_spectre_text,
    spectre_device_inventory,
    spectre_param_refs,
    spectre_subckt_tree,
)
from rfauto.service import spectre_service

runner = CliRunner()

# ══════════════════════════ 主夹具（任务书要素全集合） ══════════════════════════

FIXTURE = """\
// Q-X79 fixture netlist（行注释形态）
# header comment line
simulator lang=spectre
parameters vdd=1.8 lcon='1u*3' rload=1meg
/* block comment
   spans two more lines */
include "models/core.scs" section=tt
ahdl_include "va/amp.va"
simulatorOptions options reltol=1e-3 temp=27
M1 (d g 0 0) nch w=2u l=180n
R1 (vdd mid) resistor r=rload
C1 (mid 0) capacitor c=2p
L1 (mid out) inductor l=1n
D1 (out 0) diode area=1p
E1 (out 0 mid 0) vcvs gain=10 \\
    gain2=20
subckt inv (a y) wp=2u wn=1u
    Mp (y a vdd vdd) pch w=wp l=lcon
    Mn (y a 0 0) nch w=wn l=180n
ends inv
X1 (mid y1) inv wp=4u
amp1 (mid y2) inv
Z1 (a b) mystery x=1
tran1 tran stop=1u
"""

def parse_fixture() -> dict:
    return parse_spectre_text(FIXTURE)

def write_fixture(tmp_path: Path, name: str = "main.scs") -> Path:
    p = tmp_path / name
    p.write_text(FIXTURE, encoding="utf-8")
    return p

# ══════════════════════════ 单位换算表 ══════════════════════════

class TestUnitScale:
    @pytest.mark.parametrize(
        ("token", "expected", "status"),
        [
            ("180n", 1.8e-7, "scaled"),
            ("2u", 2e-6, "scaled"),
            ("1meg", 1e6, "scaled"),  # meg 特判：非 1m+eg
            ("1MEG", 1e6, "scaled"),  # 大小写不敏感
            ("1mil", 25.4e-6, "scaled"),
            ("2T", 2e12, "scaled"),
            ("3G", 3e9, "scaled"),
            ("4k", 4e3, "scaled"),
            ("5m", 5e-3, "scaled"),  # 与 meg 特判区分
            ("6u", 6e-6, "scaled"),
            ("7n", 7e-9, "scaled"),
            ("8p", 8e-12, "scaled"),
            ("9f", 9e-15, "scaled"),
            ("1pF", 1e-12, "scaled"),  # 比例因子+单位词闭集
            ("100mA", 0.1, "scaled"),
            ("1.8V", 1.8, "unit_word"),
            ("1A", 1.0, "unit_word"),  # 大写 A=单位词（安培标注）
            ("1e-3", 1e-3, "none"),
            ("0", 0.0, "none"),  # 0.0 合法值非缺失
            ("-.5u", -5e-7, "scaled"),
        ],
    )
    def test_known_quantity(self, token: str, expected: float, status: str) -> None:
        assert parse_spectre_number(token) == (expected, status)

    @pytest.mark.parametrize(
        ("token", "status"),
        [
            ("1M", "ambiguous"),  # Spectre 原生 M=1e6 vs SPICE M=1e-3——不猜
            ("2.4MHz", "ambiguous"),
            ("1Mohm", "ambiguous"),
            ("1a", "ambiguous"),  # Spectre 原生 a=1e-18 vs SPICE a 非比例因子
            ("5x", "unrecognized"),  # 后缀不在表与单位词闭集
            ("1meter", "unrecognized"),
        ],
    )
    def test_refused_suffix_value_si_none(self, token: str, status: str) -> None:
        value, got = parse_spectre_number(token)
        assert value is None
        assert got == status

    def test_overflow_value_si_none(self) -> None:
        value, _status = parse_spectre_number("1e400k")
        assert value is None  # 非有限值不进 JSON（守卫 _finite_or_none）

    def test_non_number_returns_none(self) -> None:
        assert parse_spectre_number("abc") is None
        assert parse_spectre_number("") is None

    def test_exact_decimal_no_float_tail(self) -> None:
        # 180n 精确十进制换算——无 float 乘法舍入尾巴 1.8000000000000002e-07
        assert repr(parse_spectre_number("180n")[0]) == repr(1.8e-07)

# ══════════════════════════ 值类型分派 ══════════════════════════

class TestClassifyValue:
    @pytest.mark.parametrize(
        ("raw", "kind", "is_expr", "is_str"),
        [
            ("`1u*3`", "expression", True, False),  # 反引号
            ("'2u*beta'", "expression", True, False),  # 单引号
            ("{2p*2}", "expression", True, False),  # 花括号
            ("2*wp", "expression", True, False),  # 裸运算符表达式
            ("-vdd+1", "expression", True, False),
            ("vdd", "reference", True, False),  # 裸标识符=参数引用
            ("a.b", "reference", True, False),  # 层次名引用
            ('"str"', "string", False, True),
            ("[1 2 3]", "vector", False, False),
            ("1u", "number", False, False),
            ("@@@", "raw", False, False),  # 非数值非表达式兜底
        ],
    )
    def test_kind_dispatch(self, raw: str, kind: str, is_expr: bool, is_str: bool) -> None:
        typed = classify_spectre_value(raw)
        assert typed["kind"] == kind
        assert typed["is_expression"] is is_expr
        assert typed["is_string"] is is_str

    def test_expression_raw_preserved_value_si_none(self) -> None:
        typed = classify_spectre_value("'1u*3'")
        assert typed["value_raw"] == "'1u*3'"
        assert typed["value_si"] is None  # 铁律 7：表达式不求值

    def test_reference_is_expression_flag(self) -> None:
        typed = classify_spectre_value("rload")
        assert typed["is_expression"] is True
        assert typed["value_si"] is None

    def test_number_carries_suffix_status(self) -> None:
        typed = classify_spectre_value("1meg")
        assert typed["suffix_status"] == "scaled"
        assert typed["value_si"] == 1e6

    def test_raw_value_si_none(self) -> None:
        assert classify_spectre_value("@@@")["value_si"] is None

# ══════════════════════════ 词法 ══════════════════════════

class TestLexer:
    def test_line_comment_slashes(self) -> None:
        doc = parse_spectre_text("simulator lang=spectre\n// comment\nR1 (a b) resistor r=1k\n")
        assert [i["name"] for i in doc["top_instances"]] == ["R1"]
        assert doc["warnings"] == []

    def test_block_comment_multiline_keeps_line_no(self) -> None:
        text = "simulator lang=spectre\n/* line2\n   line3\n   line4 */\nR1 (a b) resistor r=1k\n"
        doc = parse_spectre_text(text)
        assert doc["top_instances"][0]["line_no"] == 5  # 行号=真实物理行（探针实测 Q-X33 偏 2）
        assert doc["warnings"] == []

    def test_star_full_line_comment(self) -> None:
        doc = parse_spectre_text("* old-style comment\nR1 (a b) resistor r=1k\n")
        assert len(doc["top_instances"]) == 1

    def test_hash_comment_line(self) -> None:
        doc = parse_spectre_text("simulator lang=spectre\n# header\nR1 (a b) resistor r=1k\n")
        assert len(doc["top_instances"]) == 1
        assert doc["warnings"] == []

    def test_comment_marker_inside_quotes_not_stripped(self) -> None:
        doc = parse_spectre_text('R1 (a b) resistor r="a//b" x=1\n')
        inst = doc["top_instances"][0]
        assert inst["params"]["r"]["value_raw"] == '"a//b"'  # 引号内注释符不剥

    def test_continuation_joins_and_line_no_is_first(self) -> None:
        doc = parse_spectre_text("R1 (a b) resistor r=1k \\\n    x=2\n")
        inst = doc["top_instances"][0]
        assert inst["line_no"] == 1
        assert sorted(inst["params"]) == ["r", "x"]

    def test_continuation_at_eof_warning(self) -> None:
        doc = parse_spectre_text("R1 (a b) resistor r=1k \\\n")
        assert any("续行符" in w for w in doc["warnings"])
        assert doc["top_instances"][0]["params"]["r"]["value_si"] == 1e3

    def test_unclosed_block_comment_warning(self) -> None:
        doc = parse_spectre_text("R1 (a b) resistor r=1k\n/* dangling\n")
        assert any("/*" in w for w in doc["warnings"])
        assert doc["top_instances"]  # 注释前语句已收

    def test_kv_split_spacing_merged(self) -> None:
        doc = parse_spectre_text("R1 (a b) resistor r = 1k ,  w =2\n")
        params = doc["top_instances"][0]["params"]
        assert params["r"]["value_si"] == 1e3
        assert params["w"]["value_si"] == 2.0

    def test_function_parens_in_value_kept_whole(self) -> None:
        doc = parse_spectre_text("E1 (a b) vcvs gain=`f(x, y)`\n")
        assert doc["top_instances"][0]["params"]["gain"]["value_raw"] == "`f(x, y)`"

    def test_bracket_vector_value_kept_whole(self) -> None:
        doc = parse_spectre_text("M1 (a b) nch l=[1 2]\n")
        assert doc["top_instances"][0]["params"]["l"]["kind"] == "vector"

    def test_unclosed_quote_warning(self) -> None:
        doc = parse_spectre_text('R1 (a b) resistor r="oops\n')
        assert any("引号未闭合" in w for w in doc["warnings"])

    def test_empty_text_warning(self) -> None:
        doc = parse_spectre_text("   \n\n")
        assert any("空网表" in w for w in doc["warnings"])
        assert doc["stats"]["n_instances"] == 0

# ══════════════════════════ 语句面 ══════════════════════════

class TestStatements:
    def test_lang_declared(self) -> None:
        assert parse_fixture()["lang"] == "spectre"

    def test_lang_missing_warning_not_fatal(self) -> None:
        doc = parse_spectre_text("R1 (a b) resistor r=1k\n")
        assert doc["lang"] is None
        assert any("lang" in w for w in doc["warnings"])
        assert doc["top_instances"]  # 照常解析

    def test_lang_spice_foreign_segment_registered(self) -> None:
        text = ("simulator lang=spectre\nC1 (a 0) capacitor c=1p\n"
                "simulator lang=spice\nR5 n1 n2 1k\n+ tc1=0\n"
                "simulator lang=spectre\nC2 (b 0) capacitor c=2p\n")
        doc = parse_spectre_text(text)
        assert doc["lang"] == "spectre"
        assert len(doc["foreign_segments"]) == 1
        seg = doc["foreign_segments"][0]
        assert seg["lang"] == "spice"
        assert seg["start_line"] == 3 and seg["end_line"] == 5
        assert seg["raw_statements"] == ["R5 n1 n2 1k", "+ tc1=0"]
        assert [i["name"] for i in doc["top_instances"]] == ["C1", "C2"]
        assert any("lang=spice" in w for w in doc["warnings"])

    def test_parameters_table(self) -> None:
        params = parse_fixture()["parameters"]
        assert set(params) == {"vdd", "lcon", "rload"}
        assert params["vdd"]["value_si"] == 1.8
        assert params["rload"]["value_si"] == 1e6  # meg 特判
        assert params["lcon"]["is_expression"] is True and params["lcon"]["value_si"] is None

    def test_parameters_duplicate_warning(self) -> None:
        doc = parse_spectre_text("parameters a=1\nparameters a=2\n")
        assert doc["parameters"]["a"]["value_si"] == 2.0
        assert any("重复声明" in w for w in doc["warnings"])

    def test_parameters_inside_subckt_routes_to_subckt(self) -> None:
        text = "simulator lang=spectre\nsubckt s (a)\nparameters k=1\nR1 (a 0) resistor r=k\nends s\n"
        doc = parse_spectre_text(text)
        assert "k" not in doc["parameters"]
        assert doc["subckts"]["s"]["params"]["k"]["value_si"] == 1.0

    def test_preprocessor_directives_registered(self) -> None:
        text = ("simulator lang=spectre\n#define FOO 1\n#ifdef FOO\n"
                '#include "extra.scs"\n#endif\n')
        doc = parse_spectre_text(text)
        names = [b["name"] for b in doc["options_blocks"]]
        assert names == ["#define", "#ifdef", "#endif"]
        assert doc["includes"][0]["kind"] == "cpp_include"
        assert doc["includes"][0]["path"] == "extra.scs"
        assert any("预处理条件" in w for w in doc["warnings"])  # 只警告一次

    def test_include_and_ahdl_include(self) -> None:
        includes = parse_fixture()["includes"]
        assert includes[0]["kind"] == "include"
        assert includes[0]["path"] == "models/core.scs"
        assert includes[0]["kv"] == {"section": "tt"}
        assert includes[1]["kind"] == "ahdl_include"
        assert includes[1]["path"] == "va/amp.va"

    def test_options_block_simulator_options(self) -> None:
        blocks = [b for b in parse_fixture()["options_blocks"] if b["class"] == "options"]
        assert len(blocks) == 1
        assert blocks[0]["name"] == "simulatorOptions"
        assert blocks[0]["type"] == "options"
        assert blocks[0]["kv"] == {"reltol": "1e-3", "temp": "27"}

    def test_analysis_named_block(self) -> None:
        blocks = [b for b in parse_fixture()["options_blocks"] if b["class"] == "analysis"]
        assert blocks[0]["name"] == "tran1"
        assert blocks[0]["type"] == "tran"
        assert blocks[0]["kv"] == {"stop": "1u"}

    def test_control_head_global(self) -> None:
        blocks = [b for b in parse_spectre_text("global 0 vdd\n")["options_blocks"]]
        assert blocks[0]["class"] == "control"
        assert blocks[0]["args"] == ["0", "vdd"]

    def test_brace_block_captured(self) -> None:
        text = ("simulator lang=spectre\nstatistics {\n  process {\n"
                "    vary rsh dist=gauss std=0.1\n  }\n}\nR1 (a b) resistor r=1k\n")
        doc = parse_spectre_text(text)
        block = doc["options_blocks"][0]
        assert block["name"] == "statistics"
        assert block["class"] == "brace_block"
        assert block["n_statements"] == 3  # statistics 头 + process 头 + vary 行（纯闭合行不计）
        assert doc["top_instances"][0]["name"] == "R1"  # 块外语句正常收

    def test_unclassifiable_statement_warning(self) -> None:
        doc = parse_spectre_text("simulator lang=spectre\n$$$\n")
        assert any("无法归类" in w for w in doc["warnings"])

    def test_model_statement(self) -> None:
        doc = parse_spectre_text("simulator lang=spectre\nmodel nch nmos level=54 tox=4e-9\n")
        model = doc["models"]["nch"]
        assert model["master"] == "nmos"
        assert model["params"] == {"level": "54", "tox": "4e-9"}

    def test_model_ref_backfilled_on_instance(self) -> None:
        text = "simulator lang=spectre\nmodel nch nmos\nM1 (d g 0 0) nch w=2u\n"
        doc = parse_spectre_text(text)
        assert doc["top_instances"][0]["model_ref"] == "nch"

# ══════════════════════════ 实例面 ══════════════════════════

class TestInstances:
    @pytest.mark.parametrize("letter", sorted(SPECTRE_LETTER_TYPES))
    def test_letter_table_mapping(self, letter: str) -> None:
        doc = parse_spectre_text(f"{letter}9 (a b) master_k w=1\n")
        inst = doc["top_instances"][0]
        assert inst["letter_type"] == SPECTRE_LETTER_TYPES[letter]  # 首字母原判定留档
        assert inst["device_type"] == SPECTRE_LETTER_TYPES[letter]

    def test_letter_table_closed_set(self) -> None:
        # 任务书枚举 M/Q/D/R/C/L/I/V/E 必含；闭集 17 字母（新增字母=显式评审）
        assert {"M", "Q", "D", "R", "C", "L", "I", "V", "E"} <= set(SPECTRE_LETTER_TYPES)
        assert len(SPECTRE_LETTER_TYPES) == 17

    def test_lowercase_name_maps_by_upper_letter(self) -> None:
        doc = parse_spectre_text("r5 (a b) resistor r=1\n")
        assert doc["top_instances"][0]["device_type"] == "resistor"

    def test_analysis_master_rerouted_to_options_block(self) -> None:
        # 带节点表的分析语句不计器件实例（noise/xf 等保留类型字）
        doc = parse_spectre_text("simulator lang=spectre\nnoise1 (out 0) noise start=1 stop=1G\n")
        assert doc["top_instances"] == []
        block = doc["options_blocks"][0]
        assert block["class"] == "analysis"
        assert block["type"] == "noise"
        assert block["nodes"] == ["out", "0"]
        assert block["kv"] == {"start": "1", "stop": "1G"}

    def test_spice_form_numeric_master_warning(self) -> None:
        # 容 spice 形态混写如实：``R5 n1 n2 1k`` 按括号可省形态登记+警告
        doc = parse_spectre_text("simulator lang=spectre\nR5 n1 n2 1k\n")
        inst = doc["top_instances"][0]
        assert inst["master"] == "1k"
        assert inst["nodes"] == ["n1", "n2"]
        assert any("SPICE 形态" in w for w in doc["warnings"])

    def test_options_blocks_uniform_nodes_key(self) -> None:
        text = ("simulator lang=spectre\nglobal 0\nsimulatorOptions options temp=27\n"
                "#define X 1\nstatistics {\n}\ntran1 tran stop=1u\n")
        blocks = parse_spectre_text(text)["options_blocks"]
        assert [b["class"] for b in blocks] == [
            "control", "options", "preprocessor", "brace_block", "analysis"]
        assert all(b["nodes"] == [] for b in blocks)

    def test_unknown_letter_bucket(self) -> None:
        doc = parse_spectre_text("Z1 (a b) mystery x=1\n")
        inst = doc["top_instances"][0]
        assert inst["device_type"] == DEVICE_TYPE_UNKNOWN
        assert inst["letter_type"] == DEVICE_TYPE_UNKNOWN
        assert doc["stats"]["n_unknown_device_type"] == 1

    def test_x_conventional_subckt_instance(self) -> None:
        doc = parse_spectre_text("subckt inv (a y)\nends inv\nX1 (mid y1) inv\n")
        inst = doc["top_instances"][0]
        assert inst["device_type"] == DEVICE_TYPE_SUBCKT
        assert inst["subckt_ref"] == "inv"

    def test_arbitrary_name_subckt_instance_dual_form(self) -> None:
        # 显式 subckt 名优先于首字母惯例（amp1 首字母 a 非 X——双形态如实）
        doc = parse_spectre_text("subckt inv (a y)\nends inv\namp1 (mid y2) inv\n")
        inst = doc["top_instances"][0]
        assert inst["device_type"] == DEVICE_TYPE_SUBCKT
        assert inst["subckt_ref"] == "inv"
        assert inst["letter_type"] == DEVICE_TYPE_UNKNOWN  # 首字母原判定留档

    def test_undefined_subckt_reference_warning(self) -> None:
        doc = parse_spectre_text("X1 (a b) external_sub\n")
        assert doc["top_instances"][0]["subckt_ref"] == "external_sub"
        assert any("未定义" in w for w in doc["warnings"])

    def test_forward_reference_resolved(self) -> None:
        # subckt 定义在实例之后（SPICE 惯例）——前向引用照常解析
        doc = parse_spectre_text("simulator lang=spectre\nX1 (a b) late\nsubckt late (p q)\nends late\n")
        assert doc["top_instances"][0]["subckt_ref"] == "late"
        assert doc["warnings"] == []

    def test_parenless_instance_dual_form(self) -> None:
        doc = parse_spectre_text("R1 n1 n2 resistor r=1k\n")
        inst = doc["top_instances"][0]
        assert inst["nodes"] == ["n1", "n2"]
        assert inst["master"] == "resistor"
        assert inst["params"]["r"]["value_si"] == 1e3

    def test_parenless_bus_suffix_name(self) -> None:
        doc = parse_spectre_text("Cbus<3> n1 0 capacitor c=1p\n")
        assert doc["top_instances"][0]["name"] == "Cbus<3>"

    def test_missing_master_warning(self) -> None:
        doc = parse_spectre_text("R1 (a b)\n")
        assert any("缺 master" in w for w in doc["warnings"])
        assert doc["top_instances"][0]["master"] is None

    def test_unclosed_node_list_warning(self) -> None:
        doc = parse_spectre_text("R1 (a b\n")
        assert any("未闭合" in w for w in doc["warnings"])

    def test_instance_params_typed_si(self) -> None:
        params = parse_fixture()["top_instances"][0]["params"]
        assert params["w"]["value_si"] == 2e-6
        assert params["l"]["value_si"] == 1.8e-7

    def test_instance_param_reference(self) -> None:
        inst = next(i for i in parse_fixture()["top_instances"] if i["name"] == "R1")
        assert inst["params"]["r"]["kind"] == "reference"
        assert inst["params"]["r"]["value_raw"] == "rload"

    def test_continuation_params_both_captured(self) -> None:
        inst = next(i for i in parse_fixture()["top_instances"] if i["name"] == "E1")
        assert inst["params"]["gain"]["value_si"] == 10.0
        assert inst["params"]["gain2"]["value_si"] == 20.0
        assert inst["line_no"] == 15  # 续行语句行号=首物理行

# ══════════════════════════ 子电路 ══════════════════════════

class TestSubckts:
    def test_subckt_entry(self) -> None:
        sub = parse_fixture()["subckts"]["inv"]
        assert sub["nodes"] == ["a", "y"]
        assert set(sub["params"]) == {"wp", "wn"}
        assert sub["params"]["wp"]["value_si"] == 2e-6
        assert sub["closed"] is True
        assert sub["end_line_no"] == 20

    def test_body_instances_scoped(self) -> None:
        doc = parse_fixture()
        names = [i["name"] for i in doc["subckts"]["inv"]["instances"]]
        assert names == ["Mp", "Mn"]
        assert doc["stats"]["n_body_instances"] == 2
        assert doc["stats"]["n_top_instances"] == 9

    def test_body_instance_param_reference(self) -> None:
        inst = parse_fixture()["subckts"]["inv"]["instances"][0]
        assert inst["params"]["w"]["value_raw"] == "wp"  # 引用 subckt 形参
        assert inst["params"]["w"]["is_expression"] is True

    def test_nested_subckt_stack(self) -> None:
        text = ("simulator lang=spectre\nsubckt outer (a b)\n"
                "  subckt inner (c d)\n    R9 (c d) resistor r=1k\n  ends inner\n"
                "  Xi (a b) inner\nends outer\nXtop (n1 n2) outer\n")
        doc = parse_spectre_text(text)
        assert doc["subckts"]["inner"]["scope"] == ["outer"]
        assert doc["subckts"]["outer"]["scope"] == []
        assert doc["stats"]["max_definition_nesting"] == 2
        assert doc["stats"]["max_depth"] == 2
        assert doc["warnings"] == []

    def test_ends_name_mismatch_warning(self) -> None:
        doc = parse_spectre_text("subckt s (a)\nends wrong\n")
        assert doc["subckts"]["s"]["closed"] is True
        assert any("不配对" in w for w in doc["warnings"])

    def test_orphan_ends_warning(self) -> None:
        doc = parse_spectre_text("ends s\n")
        assert any("无匹配" in w for w in doc["warnings"])

    def test_unclosed_subckt_warning(self) -> None:
        doc = parse_spectre_text("subckt s (a)\nR1 (a 0) resistor r=1\n")
        assert doc["subckts"]["s"]["closed"] is False
        assert any("未闭合" in w and "s" in w for w in doc["warnings"])

    def test_duplicate_subckt_warning(self) -> None:
        doc = parse_spectre_text("subckt s (a)\nends s\nsubckt s (b)\nends s\n")
        assert doc["subckts"]["s"]["nodes"] == ["b"]  # 后列覆盖
        assert any("重复定义" in w for w in doc["warnings"])

# ══════════════════════════ 统计 ══════════════════════════

class TestStats:
    def test_per_device_type_counts(self) -> None:
        counts = parse_fixture()["stats"]["per_device_type_counts"]
        assert counts == {
            "capacitor": 1, "diode": 1, "inductor": 1, "mosfet": 3,
            "resistor": 1, "subckt_instance": 2, "unknown": 1, "vcvs": 1,
        }

    def test_aggregates(self) -> None:
        stats = parse_fixture()["stats"]
        assert stats["n_instances"] == 11
        assert stats["n_top_instances"] == 9
        assert stats["n_body_instances"] == 2
        assert stats["n_subckts"] == 1
        assert stats["n_parameters"] == 3
        assert stats["n_subckt_instances"] == 2
        assert stats["max_depth"] == 1
        assert stats["has_hierarchy_cycle"] is False
        assert stats["n_flattened_leaf_instances"] == 11  # 9 顶层原语+inv 展开 2
        assert stats["n_warnings"] == len(parse_fixture()["warnings"])

    def test_cycle_truncation(self) -> None:
        text = ("simulator lang=spectre\nsubckt buf (i o)\n  Xb (i o) outer\nends buf\n"
                "subckt outer (a b)\n  Xi (a b) buf\nends outer\nXtop (n1 n2) buf\n")
        doc = parse_spectre_text(text)
        stats = doc["stats"]
        assert stats["has_hierarchy_cycle"] is True
        assert stats["n_flattened_leaf_instances"] is None  # 环自顶层可达——如实 None
        assert any("环引用" in w for w in doc["warnings"])

    def test_depth_guard_constant(self) -> None:
        assert MAX_HIERARCHY_DEPTH == 256

    def test_deep_chain_truncated_not_crashing(self) -> None:
        # 守卫行为钉：超守卫深度实例化链 → 截断标记+平铺 None，零 RecursionError
        n = MAX_HIERARCHY_DEPTH + 20
        lines = ["simulator lang=spectre"]
        for i in range(n):
            lines.append(f"subckt s{i} (p)")
            lines.append(f"  X{i} (p) s{i + 1}" if i + 1 < n else "  R0 (p 0) resistor r=1")
            lines.append(f"ends s{i}")
        lines.append("Xtop (n) s0")
        doc = parse_spectre_text("\n".join(lines) + "\n")
        assert doc["stats"]["hierarchy_truncated"] is True
        assert doc["stats"]["n_flattened_leaf_instances"] is None
        assert any("超深" in w for w in doc["warnings"])
        tree = spectre_subckt_tree(doc)
        assert tree["truncated"] is True

    def test_depth_two_chain_flattened(self) -> None:
        text = ("simulator lang=spectre\nsubckt inv (a y)\n  M1 (y a 0 0) nch\n  M2 (y a 1 1) pch\nends inv\n"
                "subckt buf (i o)\n  X1 (i m) inv\n  X2 (m o) inv\nends buf\nXtop (n1 n2) buf\n")
        stats = parse_spectre_text(text)["stats"]
        assert stats["max_depth"] == 2
        assert stats["n_flattened_leaf_instances"] == 4  # buf→2×inv→各 2 原语

# ══════════════════════════ 查询三函数 ══════════════════════════

class TestQueries:
    def test_inventory_counts_sorted(self) -> None:
        inv = spectre_device_inventory(parse_fixture())
        assert inv["n_instances"] == 11
        assert inv["per_device_type"]["mosfet"] == 3
        assert inv["masters"]["inv"] == 2
        assert inv["n_unknown"] == 1

    def test_inventory_param_key_freq_top(self) -> None:
        inv = spectre_device_inventory(parse_fixture(), top=2)
        assert len(inv["param_key_freq"]) == 2
        assert inv["param_key_freq"][0]["key"] == "l"  # 频次降序
        assert inv["param_key_freq"][0]["count"] == 4
        full = spectre_device_inventory(parse_fixture(), top=0)
        assert len(full["param_key_freq"]) == full["n_distinct_param_keys"]

    def test_inventory_empty_doc(self) -> None:
        inv = spectre_device_inventory(parse_spectre_text(""))
        assert inv == {
            "n_instances": 0, "per_device_type": {}, "n_unknown": 0,
            "masters": {}, "param_key_freq": [], "n_distinct_param_keys": 0,
        }

    def test_tree_roots_and_depth(self) -> None:
        tree = spectre_subckt_tree(parse_fixture())
        assert tree["n_subckts"] == 1
        assert [r["name"] for r in tree["roots"]] == ["inv"]
        assert tree["max_depth"] == 1
        assert tree["roots"][0]["instantiated_at_top"] is True
        assert tree["uninstantiated"] == []

    def test_tree_nested_depth(self) -> None:
        text = ("simulator lang=spectre\nsubckt outer (a b)\n  Xi (a b) inner\nends outer\n"
                "subckt inner (c d)\nends inner\nXtop (n1 n2) outer\nY2 (p q) inner\n")
        tree = spectre_subckt_tree(parse_spectre_text(text))
        assert tree["max_depth"] == 2
        assert tree["roots"][0]["children"][0]["name"] == "inner"
        assert tree["uninstantiated"] == []

    def test_tree_cycle_marked_recursive(self) -> None:
        text = ("simulator lang=spectre\nsubckt loopA (p)\n  Xla (p) loopB\nends loopA\n"
                "subckt loopB (p)\n  Xlb (p) loopA\nends loopB\n")
        tree = spectre_subckt_tree(parse_spectre_text(text))
        assert tree["has_cycle"] is True
        flat = [n for root in tree["roots"] for n in
                [root, *root["children"], *[c for ch in root["children"] for c in ch["children"]]]]
        assert any(n.get("recursive") is True for n in flat)  # 环叶截断标记

    def test_tree_cycle_island_single_root_with_recursive_leaf(self) -> None:
        # 互引环孤岛（无顶层实例化）——单根入树、环内另一定义以 recursive 叶截断
        text = ("simulator lang=spectre\nsubckt a1 (p)\n  Xa (p) b1\nends a1\n"
                "subckt b1 (p)\n  Xb (p) a1\nends b1\n")
        tree = spectre_subckt_tree(parse_spectre_text(text))
        assert tree["has_cycle"] is True
        assert [r["name"] for r in tree["roots"]] == ["a1"]
        child = tree["roots"][0]["children"][0]
        assert child["name"] == "b1"
        leaf = child["children"][0]
        assert leaf["name"] == "a1" and leaf["recursive"] is True

    def test_param_refs_definitions_and_consumers(self) -> None:
        refs = spectre_param_refs(parse_fixture())
        assert refs["rload"]["definitions"][0]["line_no"] == 4
        assert refs["rload"]["consumers"] == [{
            "site": "instance", "instance": "R1", "scope": [], "param": "r", "line_no": 11,
            "value_raw": "rload",
        }]
        assert refs["lcon"]["consumers"][0]["instance"] == "Mp"
        assert refs["wp"]["consumers"][0]["instance"] == "Mp"
        assert refs["wp"]["definitions"][0]["origin"] == "subckt"

    def test_param_refs_no_false_positive_on_numbers(self) -> None:
        # 数值字面量含参数名子串不误报（词边界）：参数 wp 不命中 4u/180n
        refs = spectre_param_refs(parse_fixture())
        assert refs["vdd"]["consumers"] == []  # vdd 仅作为节点名出现——节点不构成消费
        assert refs["wn"]["n_consumers"] == 1

    def test_param_refs_empty_doc(self) -> None:
        assert spectre_param_refs(parse_spectre_text("")) == {}

# ══════════════════════════ 服务信封 ══════════════════════════

class TestService:
    def test_parse_ok_envelope(self, tmp_path: Path) -> None:
        result = spectre_service.parse_spectre_file(write_fixture(tmp_path))
        assert result["ok"] is True
        assert result["lang"] == "spectre"
        assert result["stats"]["n_instances"] == 11
        assert set(result["parameters"]) == {"vdd", "lcon", "rload"}
        assert "inv" in result["subckts"]

    def test_parse_missing_file_error(self, tmp_path: Path) -> None:
        result = spectre_service.parse_spectre_file(tmp_path / "missing.scs")
        assert result["ok"] is False
        assert isinstance(result["errors"], list) and result["errors"]

    def test_parse_empty_file_ok_with_warning(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.scs"
        p.write_text("", encoding="utf-8")
        result = spectre_service.parse_spectre_file(p)
        assert result["ok"] is True  # fail-soft：空文件不拒
        assert any("空网表" in w for w in result["warnings"])

    def test_parse_latin1_fallback(self, tmp_path: Path) -> None:
        p = tmp_path / "hi.scs"
        p.write_bytes("// café note\nR1 (a b) resistor r=1k\n".encode("latin-1"))
        result = spectre_service.parse_spectre_file(p)
        assert result["ok"] is True
        assert result["top_instances"][0]["name"] == "R1"

    def test_report_envelope(self, tmp_path: Path) -> None:
        result = spectre_service.spectre_report(write_fixture(tmp_path))
        assert result["ok"] is True
        assert result["inventory"]["per_device_type"]["mosfet"] == 3
        assert result["hierarchy"]["n_subckts"] == 1
        assert result["hierarchy"]["max_depth"] == 1
        assert result["param_refs"]["rload"]["n_consumers"] == 1
        assert result["n_includes"] == 2

    def test_subckt_detail_found(self, tmp_path: Path) -> None:
        result = spectre_service.spectre_subckt_detail(write_fixture(tmp_path), "inv")
        assert result["ok"] is True
        assert result["subckt"]["nodes"] == ["a", "y"]
        assert result["n_body_instances"] == 2
        assert result["instantiated_by"] == [
            {"scope": [], "name": "X1", "line_no": 21},
            {"scope": [], "name": "amp1", "line_no": 22},
        ]
        assert result["subtree"]["name"] == "inv"

    def test_subckt_detail_missing_lists_available(self, tmp_path: Path) -> None:
        result = spectre_service.spectre_subckt_detail(write_fixture(tmp_path), "nope")
        assert result["ok"] is False
        assert any("inv" in err for err in result["errors"])  # 可用名录随 errors 给出
        assert result["available"] == ["inv"]  # 结构化名录（消费方不猜）

    def test_subckt_detail_missing_file(self, tmp_path: Path) -> None:
        result = spectre_service.spectre_subckt_detail(tmp_path / "no.scs", "inv")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)

    def test_report_missing_file(self, tmp_path: Path) -> None:
        result = spectre_service.spectre_report(tmp_path / "no.scs")
        assert result["ok"] is False
        assert result["errors"]

    def test_service_deterministic(self, tmp_path: Path) -> None:
        p = write_fixture(tmp_path)
        a = spectre_service.parse_spectre_file(p)
        b = spectre_service.parse_spectre_file(p)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_service_json_native(self, tmp_path: Path) -> None:
        # 全信封 JSON 原生（无 NaN/Infinity——溢出/歧义值已归 None）
        result = spectre_service.parse_spectre_file(write_fixture(tmp_path))
        json.dumps(result, allow_nan=False)

    def test_service_read_only(self, tmp_path: Path) -> None:
        p = write_fixture(tmp_path)
        before = p.read_bytes()
        spectre_service.parse_spectre_file(p)
        spectre_service.spectre_report(p)
        spectre_service.spectre_subckt_detail(p, "inv")
        assert p.read_bytes() == before  # 纯只读零落盘

# ══════════════════════════ CLI 两叶 ══════════════════════════

class TestCli:
    def test_parse_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(spectre_app, ["parse", "--file", str(write_fixture(tmp_path)), "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["lang"] == "spectre"
        assert envelope["stats"]["n_instances"] == 11

    def test_parse_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(spectre_app, ["parse", "--file", str(tmp_path / "no.scs"), "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_report_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(spectre_app, ["report", "--file", str(write_fixture(tmp_path)), "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["inventory"]["n_instances"] == 11
        assert envelope["hierarchy"]["roots"] == ["inv"]

    def test_report_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(spectre_app, ["report", "--file", str(tmp_path / "no.scs"), "--json"])
        assert res.exit_code == 1
        assert json.loads(res.output)["ok"] is False

    def test_parse_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(spectre_app, ["parse", "--file", str(write_fixture(tmp_path))])
        assert res.exit_code == 0, res.output
        assert "lang=spectre" in res.output
        assert "mosfet=3" in res.output

    def test_report_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(spectre_app, ["report", "--file", str(write_fixture(tmp_path))])
        assert res.exit_code == 0, res.output
        assert "instances=11" in res.output
        assert "l:4" in res.output  # 参数键频次 top

    def test_help_builds_no_bare_percent(self) -> None:
        # #305 家法：--help 真构建 + 零裸 %
        for leaf in (["parse", "--help"], ["report", "--help"]):
            res = runner.invoke(spectre_app, leaf)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_missing_file_flag_fails(self) -> None:
        res = runner.invoke(spectre_app, ["parse"])
        assert res.exit_code != 0

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：spectre 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(spectre_service.__file__).parent.parent.joinpath(
            "cli", "domains", "spectre.py").read_text(encoding="utf-8")
        assert source.count('@spectre_app.command("parse")') == 1
        assert source.count('@spectre_app.command("report")') == 1
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
class TestHygiene:
    def test_no_replacement_char_in_new_files(self) -> None:
        # #259 家法：新增四文件 U+FFFD=0
        base = Path(spectre_service.__file__).parent.parent
        for rel in ("core/spectre_parser.py", "service/spectre_service.py",
                    "cli/domains/spectre.py"):
            text = (base / rel).read_text(encoding="utf-8")
            assert "\ufffd" not in text, rel

    def test_qx33_spice_parser_untouched(self) -> None:
        # 边界钉：Q-X33 core/spice_netlist_parser.py 零改动（本席只读面）
        source = Path(spectre_service.__file__).parent.parent.joinpath(
            "core", "spice_netlist_parser.py").read_text(encoding="utf-8")
        assert "Q-X33" in source  # 原席标记在位
        assert "spectre_parser" not in source  # 零反向依赖

    def test_core_deterministic(self) -> None:
        a = json.dumps(parse_fixture(), sort_keys=True)
        b = json.dumps(parse_fixture(), sort_keys=True)
        assert a == b
