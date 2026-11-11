"""BSDL（IEEE 1149.1 附录 A）解析内核+服务+CLI 薄壳单测（aurora_q Q-X77 席位）。

覆盖面（任务书 ≥60 条）：

- 词法：``--`` 注释收编、``""`` 转义、``&`` 级联合并、字符字面量、词内
  ``.``（``STD_1149_1_1994.all``）、杂散字符零进展守卫恒终止、未闭合
  引号/单引号 fail-soft 警告；
- 身份面：entity 名+``end`` 收口、关键字大小写不敏感（entity/attribute
  /boundary_register 全小写变体）、空文件/纯注释/无 entity/未收口致命
  （BsdlParseError=ValueError 子类）、多 entity 计数+警告、收口后尾随
  语句计数、未知语句跳过；
- port/TAP：4 信号主夹具方向+多名声+类型保形、模式闭集外如实登记、
  重复名覆盖、缺 ':' 跳过；5 TAP 识别（缺 TDO→warning 如实不全、TRST
  可选缺省零警告）、TAP_SCAN_* 属性目标识别优先+source 标注+目标不在
  port 表如实、大小写不敏感；
- PIN_MAP：总线路 ``data:(P2,P3)`` 双位置、标识符→常量一跳、
  ``PIN_MAP is PHYSICAL_PIN_MAP`` generic→缺省值→常量二跳
  （pin_map_constant 记录）、字符串直写、大小写不敏感常量命中、病态
  条目（缺 ':'/空名/空位置/括号未闭合）跳条+警告、重复引脚覆盖、
  PIN_MAP 缺失 warning；
- 指令面：INSTRUCTION_OPCODE 表（``名=位串``、无空格变体）、缺 '=' 跳
  条、非 0/1 位串保原值+警告、重复指令覆盖；INSTRUCTION_CAPTURE 位串
  校验；IDCODE 32 位 valid/长度≠32/含非 0/1 三态+警告；
- 边界主面：8 单元逐字段（num/cell_type/port/is_internal/function/safe/
  control_cell/disable_value/disable_result/n_fields）、``*`` 内部单元
  port None、7 字段 disable_result、>7 字段警告不收、<4 字段保部分、
  'Z' 引号 safe 剥引号、function 闭集外警告、缺序号病态整条跳（括号
  感知单计数）、未知 function 不炸；
- 控制链校验：健康链零警告；断链三形态（指向不存在/目标非 control*/
  缺控制序号）各一 warning+计数；BOUNDARY_LENGTH 一致性三数字（一致
  rel_diff=0.0 / 申报 6 vs 实际 8→+1/3 / 缺属性→None+warning / 非整数
  →None）；
- 查询三函数：bsdl_boundary_cells 平坦清单+拷贝安全、bsdl_cell_lookup
  （input 直接/output3 控制链关联/大小写不敏感/总线名无索引命中全部
  位/未命中 None）、bsdl_instruction_table（表+capture/idcode 摘要+
  空 doc）；
- 服务三函数信封契约（ok/error 两态、errors 恒 list[str]、不可读/空/
  无 entity→error、Latin-1 兜底、detail port 过滤+未命中带可用名录）；
- CLI（**bsdl_app 直连+局部父 Typer 自测**——共享 app 接线由主代合流
  统一，本席禁改 cli/main.py）：parse/report --json 全结构+human 紧凑
  面+失败信封同构（exit 1）+缺 --file usage 错（exit 2）+--help 真构建
  （#305）+help 字符卫生（裸 [ /未成对 % 零违例）+域叶形状钉+源码字面
  钉（两叶各带 --json）+**cli.main 零导入钉**（合流契约）。

单测零网络零真机；文件面一律 tmp_path（#144 run 湖零写入）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains.bsdl import bsdl_app
from rfauto.core.bsdl_parser import (
    BOUNDARY_FUNCTIONS,
    CONTROL_TARGET_FUNCTIONS,
    CONTROLLED_FUNCTIONS,
    IDCODE_BITS,
    PARSER_SCHEMA_VERSION,
    TAP_PORT_KEYS,
    BsdlParseError,
    _tokenize,
    bsdl_boundary_cells,
    bsdl_cell_lookup,
    bsdl_instruction_table,
    parse_bsdl,
)
from rfauto.service.bsdl_service import (
    bsdl_boundary_detail,
    bsdl_report,
    parse_bsdl_file,
)

# ── 主夹具（任务书口径：PIN_MAP 4 引脚含总线组+port TAP 面+功能信号+
#    INSTRUCTION_OPCODE 4+IDCODE 32 位+BOUNDARY_REGISTER 8 单元含 output3
#    控制链+控制单元）───────────────────────────────────────────────────
# 预声明账（逐项断言）：
#   entity DEMO_IC；n_entities=1；ports 10（4 TAP 面+clk/en/data/out_a/
#     out_b+TRST）；tap 5/5（tck 经 TAP_SCAN_CLOCK 属性，余名字匹配）
#   pins 4：TCK=[1]（一跳常量 PKG_A）/data=[P2,P3]（总线组双位置）/
#     clk=[J1]/vdd=[A1,B1]；pin_map_constant=PKG_A；跳条 0
#   instructions 4（EXTEST/SAMPLE/IDCODE/BYPASS）；capture 0001；
#     IDCODE 32 位 valid=True（三段 & 级联合并）
#   边界 8 单元：cell0 controlr(*)/cell1 clk input/cell2 en input/
#     cell3 out_a output3(cc=0,dv=1,rslt=Z)/cell4 control(*)/
#     cell5 out_b output3(cc=4,dv=0,rslt=Z)/cell6 data(0) bidir(cc=4)/
#     cell7 internal(*)；control 2/output3 2；控制链零警告
#   一致性三数字：declared=8/max+1=8/rel_diff=0.0
#   attributes_other：COMPONENT_CONFORMANCE/INSTRUCTION_LENGTH/
#     REGISTER_ACCESS（如实登记）
#   警告 0 条
SAMPLE_BSDL = """\
-- demo BSDL: aurora_q Q-X77 fixture
entity DEMO_IC is
  generic (PHYSICAL_PIN_MAP : string := "PKG_A");

  port (
    TCK  : in bit;
    TMS  : in bit;
    TDI  : in bit;
    TDO  : out bit;
    TRST : in bit;
    clk, en : in bit;
    data : inout bit_vector(0 to 1);
    out_a, out_b : out bit
  );

  use STD_1149_1_1994.all;

  attribute COMPONENT_CONFORMANCE of DEMO_IC : entity is "STD_1149_1_1993";
  attribute PIN_MAP of DEMO_IC : entity is PHYSICAL_PIN_MAP;

  constant PKG_A : PIN_MAP_STRING :=
    "TCK:1, data:(P2,P3), clk:J1, vdd:(A1,B1)";

  attribute TAP_SCAN_CLOCK of TCK : signal is (20.0e6, BOTH);
  attribute INSTRUCTION_LENGTH of DEMO_IC : entity is 4;
  attribute INSTRUCTION_OPCODE of DEMO_IC : entity is
    "EXTEST=0000, SAMPLE=0001, IDCODE=0010, BYPASS=1111";
  attribute INSTRUCTION_CAPTURE of DEMO_IC : entity is "0001";
  attribute IDCODE_REGISTER of DEMO_IC : entity is
    "0001" &
    "0101010101010101" &
    "00000110111" &
    "1";
  attribute REGISTER_ACCESS of DEMO_IC : entity is
    "BOUNDARY (EXTEST, SAMPLE), DEVICE_ID (IDCODE)";
  attribute BOUNDARY_LENGTH of DEMO_IC : entity is 8;
  attribute BOUNDARY_REGISTER of DEMO_IC : entity is
    "0 (BC_1, *, controlr, 0), " &
    "1 (BC_4, clk, input, X), " &
    "2 (BC_4, en, input, X), " &
    "3 (BC_1, out_a, output3, X, 0, 1, Z), " &
    "4 (BC_1, *, control, 1), " &
    "5 (BC_1, out_b, output3, X, 4, 0, Z), " &
    "6 (BC_7, data(0), bidir, X, 4, 0, Z), " &
    "7 (BC_0, *, internal, X)";
end DEMO_IC;
"""

PARSE_KEYS = {
    "ok", "path", "entity_name", "n_entities", "generics", "ports",
    "tap_ports", "n_tap_present", "pin_map_ref", "pin_map_constant",
    "pins", "use_clauses", "instructions", "instruction_capture",
    "idcode_register", "idcode_length", "idcode_valid", "boundary_cells",
    "boundary_length_declared", "boundary_length_max_cell_plus_1",
    "boundary_length_rel_diff", "attributes_other", "constants", "stats",
    "warnings",
}
REPORT_KEYS = {
    "ok", "path", "entity_name", "n_entities", "stats", "tap_ports",
    "n_tap_present", "pins_summary", "ports_summary",
    "instruction_summary", "boundary_summary", "warnings",
}
DETAIL_ALL_KEYS = {"ok", "path", "entity_name", "port", "cells", "n_cells",
                   "warnings"}
DETAIL_PORT_KEYS = DETAIL_ALL_KEYS | {"control_cells", "n_control_cells"}

runner = CliRunner()

def _mini(body: str, name: str = "MINI") -> dict[str, Any]:
    """最小 entity 壳+正文 → 解析 doc（内联用例拼装器）。"""
    return parse_bsdl(f"entity {name} is\n{body}\nend {name};")

def _broken_doc() -> dict[str, Any]:
    """控制链断裂+长度不一致夹具（三坏链形态+申报 6 vs 实际 8）。"""
    return parse_bsdl(
        "entity B is\n"
        "  port (TCK: in bit; TMS: in bit; TDI: in bit;"
        " o1, o2, o3: out bit; i1: in bit);\n"
        '  attribute PIN_MAP of B : entity is "TCK:1";\n'
        "  attribute BOUNDARY_LENGTH of B : entity is 6;\n"
        '  attribute BOUNDARY_REGISTER of B : entity is\n'
        '    "0 (BC_1, i1, input, X), " &\n'
        '    "1 (BC_1, o1, output3, X, 9, 1, Z), " &\n'
        '    "2 (BC_1, o2, output3, X, 0, 1, Z), " &\n'
        '    "3 (BC_1, o3, output3, X), " &\n'
        '    "4 (BC_1, *, control, 1), " &\n'
        '    "5 (BC_1, *, internal, X), " &\n'
        '    "6 (BC_1, *, internal, X), " &\n'
        '    "7 (BC_1, *, internal, X)";\n'
        "end B;")

@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return parse_bsdl(SAMPLE_BSDL)

@pytest.fixture(scope="module")
def stats(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["stats"]

@pytest.fixture()
def bsdl_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.bsd"
    f.write_text(SAMPLE_BSDL, encoding="utf-8")
    return f

@pytest.fixture(scope="module")
def local_app() -> typer.Typer:
    """局部父 Typer（共享 app 接线待主代合流；本席自测不经 cli/main）。"""
    parent = typer.Typer()
    parent.add_typer(bsdl_app, name="bsdl")
    return parent

# ── 词法（注释/转义/级联/守卫/fail-soft）──────────────────────────────

class TestLexer:
    def test_line_comment_stripped(self) -> None:
        toks, warns = _tokenize("a -- comment\nb")
        assert [v for _k, v, _l in toks] == ["a", "b"]
        assert warns == []

    def test_comment_till_eof(self) -> None:
        toks, warns = _tokenize("a -- till end")
        assert [v for _k, v, _l in toks] == ["a"]
        assert warns == []

    def test_escaped_double_quote(self) -> None:
        toks, _w = _tokenize('"say ""hi"""')
        assert toks[0][:2] == ("string", 'say "hi"')

    def test_amp_concat_joined_in_value(self, doc: dict[str, Any]) -> None:
        # 级联在取值段合并——IDCODE 四段并一串
        assert len(doc["idcode_register"]) == 32

    def test_dot_inside_word(self) -> None:
        toks, _w = _tokenize("use STD_1149_1_1994.all;")
        assert [v for _k, v, _l in toks] == ["use", "STD_1149_1_1994.all", ";"]

    def test_assign_vs_colon(self) -> None:
        toks, _w = _tokenize("a : string := \"x\"")
        assert [v for _k, v, _l in toks] == ["a", ":", "string", ":=", "x"]

    def test_char_literal_token(self) -> None:
        toks, _w = _tokenize("'0'")
        assert toks[0][:2] == ("char", "0")

    def test_lone_quote_fail_soft(self) -> None:
        toks, warns = _tokenize("a ' zz")
        assert warns and "字符字面量" in warns[0]
        assert [v for _k, v, _l in toks] == ["a", "zz"]

    def test_unterminated_string_fail_soft(self) -> None:
        _toks, warns = _tokenize('"no end')
        assert warns and "未闭合" in warns[0]

    def test_stray_chars_never_hang(self) -> None:
        # 零进展守卫：任意杂散输入恒终止（无死循环面）
        toks, _w = _tokenize("a.b # / + ? % x")
        assert [v for _k, v, _l in toks] == ["a.b", "#", "/", "+", "?", "%", "x"]

    def test_case_normalized_compare_original_kept(self, doc: dict[str, Any]) -> None:
        # 大小写归一双录：关键字比较不敏感、标识符保原值
        assert doc["entity_name"] == "DEMO_IC"

# ── 身份面（entity 头/end 收口/致命面/多 entity）──────────────────────

class TestIdentity:
    def test_schema_tag(self, doc: dict[str, Any]) -> None:
        assert doc["schema"] == f"bsdl/{PARSER_SCHEMA_VERSION}"

    def test_entity_name(self, doc: dict[str, Any]) -> None:
        assert doc["entity_name"] == "DEMO_IC"
        assert doc["n_entities"] == 1

    def test_empty_raises(self) -> None:
        with pytest.raises(BsdlParseError):
            parse_bsdl("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(BsdlParseError):
            parse_bsdl("  \n\t\r\n")

    def test_comment_only_raises(self) -> None:
        with pytest.raises(BsdlParseError):
            parse_bsdl("-- just a comment\n")

    def test_no_entity_raises(self) -> None:
        with pytest.raises(BsdlParseError) as ei:
            parse_bsdl("port (a: in bit);\n")
        assert "entity" in str(ei.value)

    def test_unterminated_entity_raises_with_line(self) -> None:
        with pytest.raises(BsdlParseError) as ei:
            parse_bsdl("entity X is\n  port (a: in bit);\n")
        assert "第 1 行" in str(ei.value)
        assert "收口" in str(ei.value)

    def test_error_is_valueerror(self) -> None:
        assert issubclass(BsdlParseError, ValueError)

    def test_lowercase_keywords_variant(self) -> None:
        d = parse_bsdl(
            "entity lc is\n"
            "  attribute pin_map of lc : entity is \"a:1\";\n"
            "  attribute boundary_length of lc : entity is 1;\n"
            "  attribute boundary_register of lc : entity is "
            "\"0 (BC_1, a, input, X)\";\n"
            "end lc;")
        assert d["entity_name"] == "lc"
        assert d["pins"] == {"a": ["1"]}
        assert d["boundary_length_declared"] == 1

    def test_multiple_entities_first_parsed(self) -> None:
        d = parse_bsdl(
            "entity A is end A;\nentity B is end B;\n")
        assert d["entity_name"] == "A"
        assert d["n_entities"] == 2
        assert any("entity" in w for w in d["warnings"])

    def test_trailing_statements_counted(self) -> None:
        d = parse_bsdl("entity A is\nattribute PIN_MAP of A : entity is "
                       "\"p:1\";\nend A;\nattribute STRAY of A : entity is "
                       "\"x\";")
        assert any("尾随" in w for w in d["warnings"])

    def test_unknown_statement_skipped_with_warning(self) -> None:
        d = _mini("  bogus_stmt x;\n")
        assert d["stats"]["n_unknown_statements"] == 1
        assert any("bogus_stmt" in w for w in d["warnings"])

    def test_deterministic(self) -> None:
        assert parse_bsdl(SAMPLE_BSDL) == parse_bsdl(SAMPLE_BSDL)

    def test_json_round_trip(self, doc: dict[str, Any]) -> None:
        assert json.loads(json.dumps(doc, ensure_ascii=False)) == doc

    def test_stats_all_int(self, doc: dict[str, Any]) -> None:
        assert all(isinstance(v, int) for v in doc["stats"].values())

# ── port/TAP 面 ───────────────────────────────────────────────────────

class TestPortTap:
    def test_ports_parsed(self, doc: dict[str, Any]) -> None:
        assert doc["stats"]["n_ports"] == 10
        assert doc["ports"]["TDO"]["dir"] == "out"
        assert doc["ports"]["data"]["dir"] == "inout"

    def test_multi_name_declaration(self, doc: dict[str, Any]) -> None:
        # 同行多名（clk, en : in bit）展开两信号
        assert doc["ports"]["clk"]["dir"] == "in"
        assert doc["ports"]["en"]["dir"] == "in"
        assert doc["ports"]["clk"]["line"] == doc["ports"]["en"]["line"]

    def test_type_preserved_with_parens(self, doc: dict[str, Any]) -> None:
        assert "bit_vector" in doc["ports"]["data"]["type"]
        assert "0 to 1" in doc["ports"]["data"]["type"]

    def test_unknown_mode_registered(self) -> None:
        d = _mini("  port (a: weird bit);\n")
        assert d["ports"]["a"]["dir"] == "weird"
        assert any("模式" in w for w in d["warnings"])

    def test_duplicate_port_override(self) -> None:
        d = _mini("  port (a: in bit; a: out bit);\n")
        assert d["ports"]["a"]["dir"] == "out"
        assert any("重复名" in w for w in d["warnings"])

    def test_port_decl_missing_colon_skipped(self) -> None:
        d = _mini("  port (a in bit);\n")
        assert d["ports"] == {}
        assert any("缺 ':'" in w for w in d["warnings"])

    def test_tap_five_identified(self, doc: dict[str, Any]) -> None:
        assert doc["n_tap_present"] == 5
        assert set(doc["tap_ports"]) == set(TAP_PORT_KEYS)
        assert doc["tap_ports"]["tdo"]["dir"] == "out"

    def test_tap_scan_attribute_priority(self, doc: dict[str, Any]) -> None:
        assert doc["tap_ports"]["tck"]["source"] == "attribute"
        assert doc["tap_ports"]["tms"]["source"] == "name"

    def test_missing_tdo_warns(self) -> None:
        d = _mini("  port (TCK: in bit; TMS: in bit; TDI: in bit);\n")
        assert d["n_tap_present"] == 3
        assert any("TDO" in w for w in d["warnings"])

    def test_trst_optional_no_warning(self, doc: dict[str, Any]) -> None:
        assert not any("TRST" in w for w in doc["warnings"])

    def test_tap_scan_target_not_in_ports_warns(self) -> None:
        d = _mini("  port (a: in bit);\n"
                  "  attribute TAP_SCAN_IN of ghost : signal is true;\n")
        assert d["tap_ports"]["tdi"]["source"] == "attribute"
        assert d["tap_ports"]["tdi"]["name"] == "ghost"
        assert any("不在 port 表" in w for w in d["warnings"])

    def test_tap_names_case_insensitive(self) -> None:
        d = _mini("  port (tck: in bit; tms: in bit; tdi: in bit;"
                  " tdo: out bit);\n")
        assert d["n_tap_present"] == 4
        assert d["tap_ports"]["tck"]["name"] == "tck"

    def test_tap_scan_missing_of_target_skipped(self) -> None:
        d = _mini("  port (a: in bit);\n"
                  "  attribute TAP_SCAN_IN is true;\n")
        assert any("缺 'of" in w for w in d["warnings"])

# ── PIN_MAP 面（总线组/一跳/二跳/病态条目）────────────────────────────

class TestPinMap:
    def test_simple_and_bus_entries(self, doc: dict[str, Any]) -> None:
        assert doc["pins"]["TCK"] == ["1"]
        assert doc["pins"]["data"] == ["P2", "P3"]
        assert doc["pins"]["vdd"] == ["A1", "B1"]

    def test_constant_indirection_one_hop(self, doc: dict[str, Any]) -> None:
        assert doc["pin_map_ref"] == "PHYSICAL_PIN_MAP"
        assert doc["pin_map_constant"] == "PKG_A"
        assert doc["stats"]["n_pins"] == 4

    def test_generic_two_hop_chain(self) -> None:
        d = parse_bsdl(
            'entity G is\n'
            '  generic (PHYSICAL_PIN_MAP : string := "PKG");\n'
            '  attribute PIN_MAP of G : entity is PHYSICAL_PIN_MAP;\n'
            '  constant PKG : PIN_MAP_STRING := "x:9, b:(L1,L2)";\n'
            'end G;')
        assert d["pin_map_constant"] == "PKG"
        assert d["pins"]["b"] == ["L1", "L2"]

    def test_direct_string_form(self) -> None:
        d = _mini('  attribute PIN_MAP of MINI : entity is "p:1, q:(R1,R2)";\n')
        assert d["pins"]["q"] == ["R1", "R2"]

    def test_constant_lookup_case_insensitive(self) -> None:
        d = _mini('  attribute PIN_MAP of MINI : entity is physical_pin_map;\n'
                  '  constant PHYSICAL_PIN_MAP : PIN_MAP_STRING := "z:2";\n')
        assert d["pin_map_constant"] == "PHYSICAL_PIN_MAP"
        assert d["pins"]["z"] == ["2"]

    def test_missing_constant_warns(self) -> None:
        d = _mini("  attribute PIN_MAP of MINI : entity is NOWHERE;\n")
        assert d["pins"] == {}
        assert any("未找到" in w or "既非常量" in w for w in d["warnings"])

    def test_missing_pin_map_attribute_warns(self) -> None:
        d = _mini("  port (a: in bit);\n")
        assert d["pins"] == {}
        assert any("PIN_MAP" in w for w in d["warnings"])

    def test_pin_map_string_fallback(self) -> None:
        d = _mini('  attribute PIN_MAP_STRING of MINI : entity is "w:5";\n')
        assert d["pins"]["w"] == ["5"]
        assert any("兜底" in w for w in d["warnings"])

    def test_malformed_entry_missing_colon_skipped(self) -> None:
        d = _mini('  attribute PIN_MAP of MINI : entity is "good:1, bad, '
                  'w:3";\n')
        assert d["pins"] == {"good": ["1"], "w": ["3"]}
        assert d["stats"]["n_pin_map_entries_skipped"] == 1
        assert any("缺 ':'" in w for w in d["warnings"])

    def test_malformed_entry_empty_pin_skipped(self) -> None:
        d = _mini('  attribute PIN_MAP of MINI : entity is ":9";\n')
        assert d["pins"] == {}
        assert d["stats"]["n_pin_map_entries_skipped"] == 1

    def test_malformed_bus_unclosed_paren_skipped(self) -> None:
        # 深度感知切分：未闭合 '(' 吞到串尾整段跳条（fail-soft 不炸全文）
        d = _mini('  attribute PIN_MAP of MINI : entity is '
                  '"a:(P1; bad:2, c:3";\n')
        assert d["pins"] == {}
        assert d["stats"]["n_pin_map_entries_skipped"] == 1
        assert any("未闭合" in w for w in d["warnings"])

    def test_unterminated_bus_then_valid_entry(self) -> None:
        # 未闭合组闭合后：下个深度 0 逗号起后续条目存活
        d = _mini('  attribute PIN_MAP of MINI : entity is '
                  '"a:(P1, b:2), c:3";\n')
        assert d["pins"] == {"a": ["P1", "b:2"], "c": ["3"]}
        assert d["stats"]["n_pin_map_entries_skipped"] == 0

    def test_duplicate_pin_override(self) -> None:
        d = _mini('  attribute PIN_MAP of MINI : entity is "a:1, a:2";\n')
        assert d["pins"]["a"] == ["2"]
        assert any("重复" in w for w in d["warnings"])

    def test_empty_bus_group_skipped(self) -> None:
        d = _mini('  attribute PIN_MAP of MINI : entity is "a:(), b:3";\n')
        assert d["pins"] == {"b": ["3"]}
        assert d["stats"]["n_pin_map_entries_skipped"] == 1

# ── 指令面（OPCODE/CAPTURE/IDCODE）────────────────────────────────────

class TestInstructions:
    def test_opcode_table(self, doc: dict[str, Any]) -> None:
        assert doc["instructions"] == {
            "EXTEST": "0000", "SAMPLE": "0001", "IDCODE": "0010",
            "BYPASS": "1111"}
        assert doc["stats"]["n_instructions"] == 4

    def test_opcode_no_space_variant(self) -> None:
        d = _mini('  attribute INSTRUCTION_OPCODE of MINI : entity is '
                  '"A=00,B=11";\n')
        assert d["instructions"] == {"A": "00", "B": "11"}
        assert not any("指令" in w or "'='" in w for w in d["warnings"])

    def test_opcode_entry_missing_eq_skipped(self) -> None:
        d = _mini('  attribute INSTRUCTION_OPCODE of MINI : entity is '
                  '"OK=10, BADX";\n')
        assert d["instructions"] == {"OK": "10"}
        assert any("缺 '='" in w for w in d["warnings"])

    def test_opcode_non_bit_chars_kept_with_warning(self) -> None:
        d = _mini('  attribute INSTRUCTION_OPCODE of MINI : entity is '
                  '"A=0X10";\n')
        assert d["instructions"]["A"] == "0X10"
        assert any("非 0/1" in w for w in d["warnings"])

    def test_opcode_duplicate_override(self) -> None:
        d = _mini('  attribute INSTRUCTION_OPCODE of MINI : entity is '
                  '"A=00, A=11";\n')
        assert d["instructions"]["A"] == "11"
        assert any("重复" in w for w in d["warnings"])

    def test_capture_valid(self, doc: dict[str, Any]) -> None:
        assert doc["instruction_capture"] == "0001"

    def test_capture_invalid_chars_warns(self) -> None:
        d = _mini('  attribute INSTRUCTION_CAPTURE of MINI : entity is '
                  '"0Z01";\n')
        assert d["instruction_capture"] == "0Z01"
        assert any("INSTRUCTION_CAPTURE" in w for w in d["warnings"])

    def test_idcode_32bit_valid(self, doc: dict[str, Any]) -> None:
        assert doc["idcode_length"] == IDCODE_BITS == 32
        assert doc["idcode_valid"] is True
        assert doc["warnings"] == []

    def test_idcode_wrong_length_warns(self) -> None:
        d = _mini('  attribute IDCODE_REGISTER of MINI : entity is "0101";\n')
        assert d["idcode_valid"] is False
        assert any("≠ 标准位宽" in w for w in d["warnings"])

    def test_idcode_invalid_chars_warns(self) -> None:
        d = _mini('  attribute IDCODE_REGISTER of MINI : entity is '
                  '"0" * 1;\n')  # 无级联：word 兜底路径外——字符串含空格
        assert any("IDCODE" in w for w in d["warnings"]) or \
            d["idcode_register"] is None

    def test_idcode_missing_no_warning_face(self) -> None:
        d = _mini("  port (a: in bit);\n")
        assert d["idcode_register"] is None and d["idcode_valid"] is None

# ── 边界主面（单元表/内部端口/字段面）─────────────────────────────────

class TestBoundaryCells:
    def test_cell_count_and_order(self, doc: dict[str, Any]) -> None:
        assert doc["stats"]["n_boundary_cells"] == 8
        assert [c["num"] for c in doc["boundary_cells"]] == list(range(8))

    def test_cell_fields_controlr_internal(self, doc: dict[str, Any]) -> None:
        c0 = doc["boundary_cells"][0]
        assert c0["cell_type"] == "BC_1"
        assert c0["port"] is None and c0["is_internal"] is True
        assert c0["function"] == "controlr" and c0["safe"] == "0"
        assert c0["n_fields"] == 4

    def test_cell_output3_full_chain(self, doc: dict[str, Any]) -> None:
        c3 = doc["boundary_cells"][3]
        assert c3["port"] == "out_a" and c3["function"] == "output3"
        assert c3["control_cell"] == 0
        assert c3["disable_value"] == "1" and c3["disable_result"] == "Z"
        assert c3["n_fields"] == 7

    def test_cell_indexed_port(self, doc: dict[str, Any]) -> None:
        c6 = doc["boundary_cells"][6]
        assert c6["port"] == "data(0)" and c6["function"] == "bidir"

    def test_counts_control_output3(self, doc: dict[str, Any]) -> None:
        assert doc["stats"]["n_control_cells"] == 2
        assert doc["stats"]["n_output3_cells"] == 2

    def test_healthy_chain_zero_warnings(self, doc: dict[str, Any]) -> None:
        assert doc["stats"]["n_control_chain_warnings"] == 0
        assert doc["warnings"] == []

    def test_quoted_safe_char_stripped(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"0 (BC_1, a, input, \'0\')";\n')
        assert d["boundary_cells"][0]["safe"] == "0"

    def test_unknown_function_warns_registered(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"0 (BC_9, a, weird_out, X)";\n')
        assert d["boundary_cells"][0]["function"] == "weird_out"
        assert any("不在已知闭集" in w for w in d["warnings"])

    def test_record_too_few_fields_partial(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"0 (BC_1, a, input)";\n')
        cell = d["boundary_cells"][0]
        assert cell["safe"] is None and cell["n_fields"] == 3
        assert any("< 4" in w for w in d["warnings"])

    def test_record_too_many_fields_warns(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"0 (BC_1, a, input, X, 9, 8, 7, 6)";\n')
        assert d["boundary_cells"][0]["n_fields"] == 8
        assert any("> 7" in w for w in d["warnings"])

    def test_non_int_control_cell_kept_none(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"0 (BC_1, a, output3, X, zz, 1, Z)";\n')
        assert d["boundary_cells"][0]["control_cell"] is None
        assert any("非整数" in w for w in d["warnings"])

    def test_garbage_entry_skipped_once(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"junk (BC_1, a, input, X), 0 (BC_1, b, input, X)";\n')
        assert [c["num"] for c in d["boundary_cells"]] == [0]
        assert d["stats"]["n_boundary_entries_skipped"] == 1

    def test_entry_missing_paren_skipped(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"0 no_paren, 1 (BC_1, b, input, X)";\n')
        assert [c["num"] for c in d["boundary_cells"]] == [1]
        assert d["stats"]["n_boundary_entries_skipped"] == 1

    def test_missing_boundary_register_empty(self) -> None:
        d = _mini("  port (a: in bit);\n")
        assert d["boundary_cells"] == []
        assert d["stats"]["n_boundary_cells"] == 0

# ── 控制链校验+一致性三数字 ────────────────────────────────────────────

@pytest.fixture(scope="module")
def broken() -> dict[str, Any]:
    return _broken_doc()

class TestControlChainAndLength:
    def test_chain_broken_missing_target(self, broken: dict[str, Any]) -> None:
        assert broken["stats"]["n_control_chain_warnings"] == 3
        assert any("指向单元不存在" in w for w in broken["warnings"])

    def test_chain_broken_non_control_target(self, broken: dict[str, Any]) -> None:
        assert any("非 control*" in w for w in broken["warnings"])

    def test_chain_broken_missing_cc(self, broken: dict[str, Any]) -> None:
        assert any("缺控制序号" in w for w in broken["warnings"])

    def test_length_mismatch_three_numbers(self, broken: dict[str, Any]) -> None:
        # 申报 6 vs max+1=8：三数字 rel_diff=(8-6)/6=+1/3（SPEF cap sum 口径）
        assert broken["boundary_length_declared"] == 6
        assert broken["boundary_length_max_cell_plus_1"] == 8
        assert broken["boundary_length_rel_diff"] == pytest.approx(2 / 6)

    def test_length_match_rel_diff_zero(self, doc: dict[str, Any]) -> None:
        assert doc["boundary_length_declared"] == 8
        assert doc["boundary_length_max_cell_plus_1"] == 8
        assert doc["boundary_length_rel_diff"] == 0.0

    def test_length_missing_attr_none(self) -> None:
        d = _mini('  attribute BOUNDARY_REGISTER of MINI : entity is '
                  '"0 (BC_1, a, input, X)";\n')
        assert d["boundary_length_declared"] is None
        assert d["boundary_length_rel_diff"] is None
        assert d["boundary_length_max_cell_plus_1"] == 1
        assert any("BOUNDARY_LENGTH" in w for w in d["warnings"])

    def test_length_non_integer_none(self) -> None:
        d = _mini('  attribute BOUNDARY_LENGTH of MINI : entity is "eight";\n')
        assert d["boundary_length_declared"] is None
        assert any("非整数" in w for w in d["warnings"])

    def test_constant_sets_shape(self) -> None:
        assert "output3" in CONTROLLED_FUNCTIONS
        assert {"control", "controlr"} <= CONTROL_TARGET_FUNCTIONS
        assert "output3" in BOUNDARY_FUNCTIONS

# ── use/attributes_other（登记面）─────────────────────────────────────

class TestRegistry:
    def test_use_clause_registered(self, doc: dict[str, Any]) -> None:
        assert doc["use_clauses"] == ["STD_1149_1_1994.all"]

    def test_attributes_other_registered(self, doc: dict[str, Any]) -> None:
        assert doc["attributes_other"]["COMPONENT_CONFORMANCE"] == \
            "STD_1149_1_1993"
        assert doc["attributes_other"]["REGISTER_ACCESS"] == \
            "BOUNDARY (EXTEST, SAMPLE), DEVICE_ID (IDCODE)"
        assert doc["attributes_other"]["INSTRUCTION_LENGTH"] == "4"

    def test_constants_registered(self, doc: dict[str, Any]) -> None:
        assert doc["constants"]["PKG_A"] == \
            "TCK:1, data:(P2,P3), clk:J1, vdd:(A1,B1)"

    def test_escaped_quote_in_attr(self) -> None:
        d = _mini('  attribute FOO of MINI : entity is "say ""hi""";\n')
        assert d["attributes_other"]["FOO"] == 'say "hi"'

# ── 查询三函数 ────────────────────────────────────────────────────────

class TestQueries:
    def test_boundary_cells_flat_copy(self, doc: dict[str, Any]) -> None:
        cells = bsdl_boundary_cells(doc)
        assert len(cells) == 8
        cells[0]["num"] = 999
        assert doc["boundary_cells"][0]["num"] == 0  # 拷贝安全

    def test_lookup_input_direct(self, doc: dict[str, Any]) -> None:
        hit = bsdl_cell_lookup(doc, "clk")
        assert hit is not None
        assert hit["n_cells"] == 1
        assert hit["cells"][0]["function"] == "input"
        assert hit["n_control_cells"] == 0

    def test_lookup_output3_control_chain(self, doc: dict[str, Any]) -> None:
        hit = bsdl_cell_lookup(doc, "out_a")
        assert hit["cells"][0]["num"] == 3
        assert hit["control_cells"][0]["num"] == 0
        assert hit["control_cells"][0]["function"] == "controlr"

    def test_lookup_case_insensitive(self, doc: dict[str, Any]) -> None:
        assert bsdl_cell_lookup(doc, "OUT_A") is not None
        assert bsdl_cell_lookup(doc, "CLK") is not None

    def test_lookup_bus_name_hits_all_bits(self, doc: dict[str, Any]) -> None:
        d = parse_bsdl(
            "entity M is\n"
            '  attribute BOUNDARY_REGISTER of M : entity is\n'
            '    "0 (BC_1, d(0), bidir, X, 2, 0, Z), " &\n'
            '    "1 (BC_1, d(1), bidir, X, 2, 0, Z), " &\n'
            '    "2 (BC_1, *, control, 0)";\n'
            "end M;")
        hit = bsdl_cell_lookup(d, "d")
        assert hit["n_cells"] == 2
        assert {c["port"] for c in hit["cells"]} == {"d(0)", "d(1)"}
        assert hit["control_cells"][0]["num"] == 2
        hit0 = bsdl_cell_lookup(d, "d(0)")
        assert hit0["n_cells"] == 1 and hit0["cells"][0]["port"] == "d(0)"

    def test_lookup_miss_none(self, doc: dict[str, Any]) -> None:
        assert bsdl_cell_lookup(doc, "nope") is None
        assert bsdl_cell_lookup(doc, "*") is None  # 内部单元不可寻址

    def test_instruction_table(self, doc: dict[str, Any]) -> None:
        table = bsdl_instruction_table(doc)
        assert table["n_instructions"] == 4
        assert table["capture"] == "0001"
        assert table["capture_length"] == 4
        assert table["idcode_length"] == 32
        assert table["idcode_valid"] is True

    def test_instruction_table_empty_doc(self) -> None:
        d = _mini("  port (a: in bit);\n")
        table = bsdl_instruction_table(d)
        assert table == {
            "instructions": {}, "n_instructions": 0, "capture": None,
            "capture_length": None, "idcode": None, "idcode_length": None,
            "idcode_valid": None}

# ── 服务三函数（AU-2 信封契约）─────────────────────────────────────────

class TestService:
    def test_parse_ok_envelope_keys(self, bsdl_file: Path) -> None:
        r = parse_bsdl_file(bsdl_file)
        assert r["ok"] is True
        assert set(r) == PARSE_KEYS
        assert r["path"] == str(bsdl_file)
        assert r["stats"]["n_boundary_cells"] == 8

    def test_parse_envelope_json_safe(self, bsdl_file: Path) -> None:
        json.dumps(parse_bsdl_file(bsdl_file), ensure_ascii=False)  # 不抛即过

    def test_parse_unreadable_error(self, tmp_path: Path) -> None:
        r = parse_bsdl_file(tmp_path / "no_such.bsd")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert "不可读" in r["errors"][0]

    def test_parse_empty_file_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.bsd"
        f.write_text("", encoding="utf-8")
        r = parse_bsdl_file(f)
        assert r["ok"] is False
        assert "解析失败" in r["errors"][0]

    def test_parse_no_entity_error(self, tmp_path: Path) -> None:
        f = tmp_path / "noent.bsd"
        f.write_text("port (a: in bit);\n", encoding="utf-8")
        r = parse_bsdl_file(f)
        assert r["ok"] is False
        assert "entity" in r["errors"][0]

    def test_parse_unterminated_entity_error(self, tmp_path: Path) -> None:
        f = tmp_path / "trunc.bsd"
        f.write_text("entity X is\nport (a: in bit);\n", encoding="utf-8")
        r = parse_bsdl_file(f)
        assert r["ok"] is False
        assert "收口" in r["errors"][0]

    def test_report_envelope(self, bsdl_file: Path) -> None:
        r = bsdl_report(bsdl_file)
        assert r["ok"] is True
        assert set(r) == REPORT_KEYS
        assert r["instruction_summary"]["n_instructions"] == 4
        bnd = r["boundary_summary"]
        assert bnd["n_cells"] == 8
        assert bnd["length_declared"] == 8
        assert bnd["length_max_cell_plus_1"] == 8
        assert bnd["length_rel_diff"] == 0.0
        assert bnd["function_buckets"]["output3"] == 2
        assert bnd["function_buckets"]["input"] == 2

    def test_report_unreadable_error(self, tmp_path: Path) -> None:
        r = bsdl_report(tmp_path / "missing.bsd")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)

    def test_report_failure_with_chain_warnings(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.bsd"
        f.write_text(
            "entity B is\n"
            '  attribute BOUNDARY_REGISTER of B : entity is\n'
            '    "0 (BC_1, a, input, X), 1 (BC_1, o, output3, X, 7, 1, Z)";\n'
            "end B;", encoding="utf-8")
        r = bsdl_report(f)
        assert r["ok"] is True
        assert r["stats"]["n_control_chain_warnings"] == 1

    def test_detail_all_cells(self, bsdl_file: Path) -> None:
        r = bsdl_boundary_detail(bsdl_file)
        assert r["ok"] is True
        assert set(r) == DETAIL_ALL_KEYS
        assert r["port"] is None
        assert r["n_cells"] == 8

    def test_detail_port_filter(self, bsdl_file: Path) -> None:
        r = bsdl_boundary_detail(bsdl_file, "out_b")
        assert r["ok"] is True
        assert set(r) == DETAIL_PORT_KEYS
        assert r["cells"][0]["num"] == 5
        assert r["control_cells"][0]["num"] == 4

    def test_detail_miss_lists_available(self, bsdl_file: Path) -> None:
        r = bsdl_boundary_detail(bsdl_file, "ghost_port")
        assert r["ok"] is False
        assert "ghost_port" in r["errors"][0]
        assert "out_a" in r["errors"][0]

    def test_detail_unreadable_error(self, tmp_path: Path) -> None:
        r = bsdl_boundary_detail(tmp_path / "missing.bsd", "a")
        assert r["ok"] is False
        assert "不可读" in r["errors"][0]

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.bsd"
        f.write_bytes(
            b"entity L is\n-- caf\xe9 note\nend L;\n")
        r = parse_bsdl_file(f)
        assert r["ok"] is True
        assert r["entity_name"] == "L"

    def test_service_deterministic(self, bsdl_file: Path) -> None:
        assert parse_bsdl_file(bsdl_file) == parse_bsdl_file(bsdl_file)

# ── CLI（bsdl_app 直连/局部父 Typer 自测；接线待合流）──────────────────

class TestCli:
    def test_parse_json_envelope(self, local_app: typer.Typer,
                                 bsdl_file: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "parse", "--file",
                                      str(bsdl_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == PARSE_KEYS
        assert payload["stats"]["n_boundary_cells"] == 8

    def test_parse_human_output(self, local_app: typer.Typer,
                                bsdl_file: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "parse", "--file",
                                      str(bsdl_file)])
        assert r.exit_code == 0, r.output
        assert "DEMO_IC" in r.output
        assert "out_a" in r.output
        assert "controlr" in r.output

    def test_parse_failure_json_exit1(self, local_app: typer.Typer,
                                      tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "parse", "--file",
                                      str(tmp_path / "nope.bsd"), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert len(payload["errors"]) == 1

    def test_parse_failure_human_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "parse", "--file",
                                      str(tmp_path / "nope.bsd")])
        assert r.exit_code == 1
        assert "BSDL 解析失败" in r.output

    def test_parse_missing_file_option_exit2(self,
                                             local_app: typer.Typer) -> None:
        r = runner.invoke(local_app, ["bsdl", "parse"])
        assert r.exit_code == 2

    def test_report_json_envelope(self, local_app: typer.Typer,
                                  bsdl_file: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "report", "--file",
                                      str(bsdl_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert set(payload) == REPORT_KEYS
        assert payload["boundary_summary"]["n_cells"] == 8

    def test_report_human_output(self, local_app: typer.Typer,
                                 bsdl_file: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "report", "--file",
                                      str(bsdl_file)])
        assert r.exit_code == 0, r.output
        assert "EXTEST" in r.output
        assert "output3" in r.output
        assert "declared=8" in r.output

    def test_report_failure_json_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "report", "--file",
                                      str(tmp_path / "nope.bsd"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_report_failure_human_exit1(self, local_app: typer.Typer,
                                        tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["bsdl", "report", "--file",
                                      str(tmp_path / "nope.bsd")])
        assert r.exit_code == 1
        assert "BSDL 报告失败" in r.output

    @pytest.mark.parametrize("leaf", ["parse", "report"])
    def test_help_real_build(self, local_app: typer.Typer, leaf: str) -> None:
        # #305：真构建 --help（帮助串含 % 或裸 [ 会在展开期炸/渲染歪）
        r = runner.invoke(local_app, ["bsdl", leaf, "--help"])
        assert r.exit_code == 0, r.output
        assert "--file" in r.output

    def test_direct_app_help(self) -> None:
        r = runner.invoke(bsdl_app, ["--help"])
        assert r.exit_code == 0, r.output
        assert "parse" in r.output and "report" in r.output

    def test_domain_leaf_shape(self, local_app: typer.Typer) -> None:
        from typer.main import get_command

        group = get_command(local_app).commands.get("bsdl")
        assert group is not None
        assert set(group.commands) == {"parse", "report"}

    def test_help_text_hygiene(self, local_app: typer.Typer) -> None:
        # D-06 门同判定面预检：命令 help/short_help 与参数 help 零裸 [、
        # 零未成对 %（合流后进全树门亦绿）
        from typer.main import get_command

        group = get_command(local_app).commands["bsdl"]
        texts = [group.help or ""]
        for cmd in group.commands.values():
            texts.extend([cmd.help or "", cmd.short_help or ""])
            texts.extend(getattr(p, "help", None) or "" for p in cmd.params)
        for text in texts:
            assert "[" not in text, text
            assert text.replace("%%", "").count("%") == 0, text

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：bsdl 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(
            __import__("rfauto.service.bsdl_service", fromlist=["x"])
            .__file__).parent.parent.joinpath(
            "cli", "domains", "bsdl.py").read_text(encoding="utf-8")
        assert source.count('@bsdl_app.command("parse")') == 1
        assert source.count('@bsdl_app.command("report")') == 1
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
class TestEncodingHygiene:
    @pytest.mark.parametrize("relpath", [
        "src/rfauto/core/bsdl_parser.py",
        "src/rfauto/service/bsdl_service.py",
        "src/rfauto/cli/domains/bsdl.py",
        "tests/unit/test_bsdl_parser.py",
    ])
    def test_no_replacement_char(self, relpath: str) -> None:
        # 仓根=tests/unit/test_bsdl_parser.py 的 parents[2]
        repo = Path(__file__).resolve().parents[2]
        p = repo / relpath
        text = p.read_text(encoding="utf-8")
        assert "\ufffd" not in text, f"{p} 含 U+FFFD 替换字符"
