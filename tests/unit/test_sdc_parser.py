"""SDC（Synopsys Design Constraints）解析内核单测（aurora_q Q-X36 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之解析内核半边——命令面各 ≥2+Tcl 语法负例）：
- 夹具正例：create_clock 显式名/无名自动派生、create_generated_clock
  divide_by/multiply_by、set_clock_latency/-uncertainty、input/output
  delay min/max 成对+无旗标双边形、false_path/multicycle/max_delay/
  min_delay（-from/-through/-to）、set_load 两形态、set_driving_cell、
  set_fanout_load、set_case_analysis 数值+词形态、顶层独立 get_ports、
  面外命令 warnings、variables 终态、schema 键集、stats；
- 内联正例（Tcl 词法面）：引号词含空白、花括号零替换、嵌套花括号、
  方括号子脚本提取、$var/${var} 替换、未定义变量保留原文、行连续、
  命令位注释、;# 行尾注释、分号多命令一行、引号内转义、负数值不被
  当旗标、词中 script 拼接；
- 负例（SdcParseError）：引号/花括号/方括号未闭合。

单测零网络零真机零写盘（夹具只读；负例用内联字符串）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core.sdc_parser import (
    SDC_COMMANDS,
    SdcParseError,
    TclCommand,
    TclWord,
    as_number,
    parse_sdc,
    parse_tcl,
)

FIXTURE = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "sdc" / "sample.sdc"


@pytest.fixture(scope="module")
def doc() -> dict:
    return parse_sdc(FIXTURE.read_text(encoding="utf-8"))


# ── Tcl 词法面（内联）──────────────────────────────────────────────────────


class TestTclLexer:
    def _one(self, text: str) -> TclCommand:
        cmds = parse_tcl(text)
        assert len(cmds) == 1
        return cmds[0]

    def test_quoted_word_keeps_spaces(self) -> None:
        cmd = self._one('create_clock -name "clk main" -period 5')
        assert cmd.args[1].value == "clk main"
        assert cmd.args[1].kind == "quoted"

    def test_brace_word_no_substitution(self) -> None:
        cmd = self._one("set x {a $undefined_var}")
        assert cmd.args[1].value == "a $undefined_var"
        assert cmd.args[1].literal is True

    def test_nested_braces_balance(self) -> None:
        cmd = self._one("set x {a {b {c}} d}")
        assert cmd.args[1].value == "a {b {c}} d"

    def test_brace_word_multiline(self) -> None:
        cmd = self._one("set x {a\nb\nc}")
        assert cmd.args[1].value == "a\nb\nc"

    def test_bracket_script_extracted(self) -> None:
        cmd = self._one("set x [get_ports {p1, p2}]")
        word = cmd.args[1]
        assert word.scripts == ("get_ports {p1, p2}",)
        assert word.value == "[get_ports {p1, p2}]"

    def test_var_substitution_set_then_ref(self) -> None:
        doc_vars = parse_sdc("set period 7.5\ncreate_clock -period $period")
        assert doc_vars["variables"] == {"period": "7.5"}
        assert doc_vars["clocks"][0]["period"] == pytest.approx(7.5)

    def test_braced_var_form(self) -> None:
        variables: dict[str, str] = {"io_ref": "sys"}
        parse_tcl("set p ${io_ref}", variables)
        # 环境可读回终态（外部初值+set 新增键同表）
        assert variables == {"io_ref": "sys", "p": "sys"}

    def test_undefined_var_kept_literal(self) -> None:
        cmd = self._one("set x $nope_not_defined")
        assert cmd.args[1].value == "$nope_not_defined"

    def test_backslash_newline_continuation(self) -> None:
        text = "set_load -cap 0.1 \\\n  [get_nets n1]"
        cmd = parse_tcl(text)[0]
        assert cmd.name == "set_load"
        assert cmd.args[2].scripts == ("get_nets n1",)
        assert cmd.line == 1

    def test_comment_at_command_position(self) -> None:
        cmds = parse_tcl("# 注释行\nset x 1")
        assert len(cmds) == 1
        assert cmds[0].name == "set"
        assert cmds[0].line == 2

    def test_trailing_comment_after_semicolon(self) -> None:
        cmd = parse_tcl("set x 1 ;# 行尾注释")[0]
        assert cmd.name == "set"
        assert len(cmd.args) == 2

    def test_semicolon_splits_commands_one_line(self) -> None:
        cmds = parse_tcl("set a 1; set b 2")
        assert [c.name for c in cmds] == ["set", "set"]
        assert cmds[1].args[0].value == "b"

    def test_word_hash_is_literal(self) -> None:
        cmd = self._one("set x net#1")
        assert cmd.args[1].value == "net#1"

    def test_escaped_quote_inside_quoted(self) -> None:
        cmd = self._one('set x "a\\"b"')
        assert cmd.args[1].value == 'a"b'

    def test_word_concat_with_script(self) -> None:
        cmd = self._one("set_max_delay 5 -to pad[get_cells u1]")
        flags, positional = cmd.flag_map()
        assert flags["to"].scripts == ("get_cells u1",)
        assert flags["to"].value == "pad[get_cells u1]"
        assert [p.value for p in positional] == ["5"]

    def test_negative_number_not_flag(self) -> None:
        cmd = self._one("set_max_delay -1.5")
        flags, positional = cmd.flag_map()
        assert flags == {}
        assert [p.value for p in positional] == ["-1.5"]

    def test_as_number_types(self) -> None:
        assert as_number("10") == 10
        assert isinstance(as_number("10"), int)
        assert as_number("2.5") == pytest.approx(2.5)
        assert as_number("-3e-1") == pytest.approx(-0.3)
        assert as_number("rising") is None

    def test_raw_captured(self) -> None:
        cmd = self._one("create_clock -period 5")
        assert "create_clock -period 5" in cmd.raw


class TestTclLexerNegatives:
    @pytest.mark.parametrize(
        ("text", "frag"),
        [
            ('create_clock -name "unclosed', "引号词未闭合"),
            ("create_clock {unclosed", "花括号词未闭合"),
            ("create_clock [unclosed", "方括号子命令未闭合"),
            ("set x ${unclosed_var", "变量名花括号未闭合"),
        ],
    )
    def test_unclosed_raises_with_line(self, text: str, frag: str) -> None:
        with pytest.raises(SdcParseError, match=frag):
            parse_sdc(text)

    def test_error_is_valueerror_subclass(self) -> None:
        assert issubclass(SdcParseError, ValueError)


# ── SDC 命令面（夹具）──────────────────────────────────────────────────────


class TestClockFace:
    def test_create_clock_named_full(self, doc: dict) -> None:
        clk = doc["clocks"][0]
        assert clk["kind"] == "primary"
        assert clk["name"] == "sys_clk"
        assert clk["auto_named"] is False
        assert clk["period"] == pytest.approx(10.0)
        assert clk["waveform"] == [0.0, 5.0]
        assert clk["sources"]["kind"] == "ports"
        assert clk["sources"]["patterns"] == ["clk_p", "clk_n"]

    def test_create_clock_auto_named_from_source(self, doc: dict) -> None:
        clk = doc["clocks"][1]
        assert clk["name"] == "ref_in"
        assert clk["auto_named"] is True
        assert clk["period"] == pytest.approx(25.0)

    def test_create_generated_clock_divide_by(self, doc: dict) -> None:
        clk = next(c for c in doc["clocks"] if c["name"] == "div2_clk")
        assert clk["kind"] == "generated"
        assert clk["divide_by"] == 2
        assert clk["multiply_by"] is None
        assert clk["source"]["kind"] == "ports"
        assert clk["source"]["patterns"] == ["clk_p"]

    def test_create_generated_clock_multiply_by(self, doc: dict) -> None:
        clk = next(c for c in doc["clocks"] if c["name"] == "x2_clk")
        assert clk["multiply_by"] == 2
        assert clk["divide_by"] is None
        assert clk["master_clock"] == "sys_clk"

    def test_generated_clock_line_continuation_parsed(self, doc: dict) -> None:
        clk = next(c for c in doc["clocks"] if c["name"] == "div2_clk")
        assert clk["source"]["patterns"] == ["clk_p"]  # 行连续后 -source 仍收


class TestClockNetworkFace:
    def test_set_clock_latency_source_late(self, doc: dict) -> None:
        lat = doc["constraints"]["clock_latency"][0]
        assert lat["source"] is True
        assert lat["late"] is True
        assert lat["early"] is False
        assert lat["value"] == pytest.approx(0.35)
        assert lat["objects"]["patterns"] == ["sys_clk", "div2_clk"]

    def test_set_clock_uncertainty_setup(self, doc: dict) -> None:
        unc = doc["constraints"]["clock_uncertainty"][0]
        assert unc["setup"] is True
        assert unc["hold"] is False
        assert unc["value"] == pytest.approx(0.12)
        assert unc["objects"]["patterns"] == ["sys_clk"]


class TestIODelayFace:
    def test_input_delay_min_max_pair(self, doc: dict) -> None:
        inputs = [d for d in doc["delays"] if d["type"] == "input"]
        assert len(inputs) == 3
        assert inputs[0]["max"] is True and inputs[0]["min"] is False
        assert inputs[0]["value"] == pytest.approx(3.2)
        assert inputs[1]["min"] is True and inputs[1]["max"] is False
        assert inputs[1]["value"] == pytest.approx(1.1)
        assert inputs[0]["from"]["patterns"] == ["rf_in"]

    def test_input_delay_plain_sets_both_bounds(self, doc: dict) -> None:
        entry = doc["delays"][2]
        assert entry["type"] == "input"
        assert entry["max"] is True and entry["min"] is True
        assert entry["value"] == pytest.approx(2.4)
        # ${io_ref_clk} 变量替换 → sys_clk
        assert entry["clock"] == "sys_clk"

    def test_output_delay_pair(self, doc: dict) -> None:
        outputs = [d for d in doc["delays"] if d["type"] == "output"]
        assert len(outputs) == 2
        assert outputs[0]["value"] == pytest.approx(1.8)
        assert outputs[0]["max"] is True and outputs[0]["min"] is False
        assert outputs[1]["value"] == pytest.approx(0.6)
        assert outputs[1]["min"] is True


class TestPathFace:
    def test_false_path_from_ports_to_cells(self, doc: dict) -> None:
        fp = doc["paths"][0]
        assert fp["type"] == "false_path"
        assert fp["from"]["kind"] == "ports"
        assert fp["from"]["patterns"] == ["async_rst"]
        assert fp["to"]["kind"] == "cells"
        assert fp["to"]["patterns"] == ["rst_sync*"]
        assert fp["through"] is None

    def test_false_path_mirror_bucket(self, doc: dict) -> None:
        mirror = doc["constraints"]["false_paths"]
        assert len(mirror) == 1
        assert mirror[0]["from"]["patterns"] == ["async_rst"]

    def test_multicycle_setup_end(self, doc: dict) -> None:
        mc = doc["constraints"]["multicycles"][0]
        assert mc["multiplier"] == 3
        assert mc["setup"] is True and mc["hold"] is False
        assert mc["reference"] == "end"
        assert mc["from"]["kind"] == "pins"
        assert mc["to"]["patterns"] == ["capture/D"]

    def test_max_delay_value_and_endpoints(self, doc: dict) -> None:
        md = doc["paths"][1]
        assert md["type"] == "max_delay"
        assert md["value"] == pytest.approx(6.5)
        assert md["from"]["patterns"] == ["u_pll"]
        assert md["to"]["kind"] == "ports"

    def test_min_delay_through_three_point(self, doc: dict) -> None:
        md = doc["paths"][2]
        assert md["type"] == "min_delay"
        assert md["value"] == pytest.approx(0.8)
        assert md["through"]["kind"] == "cells"
        assert md["through"]["patterns"] == ["u_amp"]


class TestConstraintFace:
    def test_set_load_capacitance(self, doc: dict) -> None:
        load = doc["constraints"]["loads"][0]
        assert load["capacitance"] == pytest.approx(0.08)
        assert load["pin_count"] is None
        assert load["objects"]["kind"] == "nets"
        assert load["objects"]["patterns"] == ["ant_net", "mixer_out"]

    def test_set_load_pin_count(self, doc: dict) -> None:
        load = doc["constraints"]["loads"][1]
        assert load["pin_count"] == 4
        assert load["capacitance"] is None

    def test_set_driving_cell(self, doc: dict) -> None:
        cell = doc["constraints"]["driving_cells"][0]
        assert cell["lib_cell"] == "BUFX4"
        assert cell["pin"] == "Z"
        assert cell["objects"]["patterns"] == ["data_bus"]

    def test_set_fanout_load(self, doc: dict) -> None:
        fo = doc["constraints"]["fanout_loads"][0]
        assert fo["value"] == 3
        assert fo["objects"]["patterns"] == ["test_en"]

    def test_set_case_analysis_numeric_and_word(self, doc: dict) -> None:
        cases = doc["constraints"]["case_analyses"]
        assert cases[0]["value"] == 1
        assert cases[1]["value"] == 0
        assert cases[0]["objects"]["patterns"] == ["band_sel0"]


class TestObjectsAndSchema:
    def test_standalone_get_ports_collected(self, doc: dict) -> None:
        ports = doc["objects"]["ports"]
        assert ports[-1]["patterns"] == ["aux_pad", "cal_pad"]

    def test_document_schema_keys(self, doc: dict) -> None:
        assert set(doc) >= {
            "clocks", "delays", "paths", "constraints", "objects",
            "variables", "commands", "warnings", "stats",
        }
        assert set(doc["constraints"]) >= {
            "loads", "driving_cells", "fanout_loads", "case_analyses",
            "false_paths", "multicycles", "clock_latency",
            "clock_uncertainty",
        }
        assert set(doc["objects"]) >= {
            "ports", "pins", "cells", "nets", "clocks",
        }

    def test_variables_terminal_state(self, doc: dict) -> None:
        assert doc["variables"] == {"clk_period": "10.0",
                                    "io_ref_clk": "sys_clk"}

    def test_unknown_command_into_warnings(self, doc: dict) -> None:
        names = [w["name"] for w in doc["warnings"]]
        assert names == ["current_design"]
        assert doc["warnings"][0]["line"] > 0

    def test_stats_counts(self, doc: dict) -> None:
        stats = doc["stats"]
        assert stats["n_clocks"] == 4
        assert stats["n_delays"] == 5
        assert stats["n_paths"] == 3
        assert stats["n_warnings"] == 1
        assert stats["n_commands"] == len(doc["commands"])

    def test_command_lines_recorded(self, doc: dict) -> None:
        assert doc["commands"][0] == {
            "name": "set", "line": 20, "arg_count": 2}

    def test_command_face_registry_covers_brief(self) -> None:
        # 任务书命令面 16 命令全部在注册表
        for name in (
            "create_clock", "create_generated_clock", "set_clock_latency",
            "set_clock_uncertainty", "set_input_delay", "set_output_delay",
            "set_false_path", "set_multicycle_path", "set_max_delay",
            "set_min_delay", "set_load", "set_driving_cell",
            "set_fanout_load", "set_case_analysis", "get_ports", "get_pins",
            "get_cells", "get_nets",
        ):
            assert name in SDC_COMMANDS

    def test_inline_multicycle_through(self) -> None:
        d = parse_sdc(
            "set_multicycle_path -setup 2 -from [get_ports a] "
            "-through [get_pins m/Z] -to [get_ports b]")
        mc = d["constraints"]["multicycles"][0]
        assert mc["multiplier"] == 2
        assert mc["through"]["patterns"] == ["m/Z"]

    def test_inline_accessor_flag_not_a_pattern(self) -> None:
        d = parse_sdc("get_ports -filter {NAME =~ A} {pad*}")
        assert d["objects"]["ports"][0]["patterns"] == ["pad*"]

    def test_accessor_filter_recorded_in_spec(self) -> None:
        spec = parse_sdc("set_load -cap 0.1 [get_nets -filter {C > 0}]")
        obj = spec["constraints"]["loads"][0]["objects"]
        assert obj["kind"] == "nets"
        assert obj["filters"] == ["-filter"]


class TestTclWordValue:
    def test_value_joins_parts(self) -> None:
        word = TclWord(kind="mixed", parts=(("text", "clk"), ("script", "get_cells u1")))
        assert word.value == "clk[get_cells u1]"
        assert word.scripts == ("get_cells u1",)

    def test_flag_map_boolean_keeps_value_positional(self) -> None:
        cmd = TclCommand(
            name="set_input_delay",
            args=(
                TclWord(kind="bare", parts=(("text", "-clock"),)),
                TclWord(kind="bare", parts=(("text", "clk"),)),
                TclWord(kind="bare", parts=(("text", "-max"),)),
                TclWord(kind="bare", parts=(("text", "2.0"),)),
            ),
            line=1,
            raw="",
        )
        flags, positional = cmd.flag_map(
            boolean_flags=frozenset({"-max"}))
        assert flags["clock"].value == "clk"
        assert flags["max"] is True
        assert [p.value for p in positional] == ["2.0"]
