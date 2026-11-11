"""SDF 解析内核+服务+CLI 单测（aurora_q 席位 Q-X61，2026-11-07）。

夹具纪律（任务书口径）：内嵌小 SDF 文本——``SDF_MAIN``=头部全量（IEEE 1497
十一键全集+非标准 CELLDIVIDER 走未知头部键路径）+块注释/行注释+2 CELL
（cell1 DFF_X1：IOPATH 2（其一带 COND）+INTERCONNECT 1+SETUP/HOLD/WIDTH 各
1；cell2 BUF_X2：INSTANCE 通配 ``*``+PORT 1+空槽三元组）；变体形态（top-level/
INCREMENT/RETAIN/脉冲限值/CONDELSE/SETUPHOLD+SCOND/CCOND/端口 COND/PATHPULSE/
面外构造）以测试内小片段覆盖。零外部夹具文件；服务/CLI 测试经 tmp_path 落盘
隔离（#144 run 湖零写入），零网络零真机。

覆盖面（任务书 ≥60 条）：S 表达式（嵌套/字符串/注释/深度守卫/失配）、TIMESCALE
表驱动换算（18 档全表+已知量+fail-closed）、三元组（三值/单值/空槽 None/非法）、
CELL 段逐类（IOPATH/COND/INTERCONNECT/SETUP/HOLD/WIDTH/PORT/通配实例）、查询
三函数（lookup top-level/通配/精确、paths 平坦清单排序稳定、timcheck 最坏值）、
服务信封三函数、CLI 两叶 --json 双路径（CliRunner 直连 sdf_app——不触共享 app，
零金快照漂移）+help 真构建+计数链字面钉+cli.main 零导入钉。
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains.sdf import sdf_app
from rfauto.core.sdf_parser import (
    DELAY_KINDS,
    EDGE_IDENTIFIERS,
    HEADER_KEYWORDS,
    MAX_NEST_DEPTH,
    TIMESCALE_FACTORS,
    TIMING_CHECK_KINDS,
    SdfAtom,
    SdfList,
    SdfParseError,
    parse_sdf,
    parse_sdf_triple,
    parse_sexpr,
    render_sexpr,
    sdf_cell_lookup,
    sdf_celltype_summary,
    sdf_delay_paths,
    sdf_timescale_factor,
    sdf_timing_check_summary,
    sexpr_to_plain,
)
from rfauto.service import sdf_service

runner = CliRunner()

# ══════════════════════════ 夹具 ══════════════════════════

SDF_MAIN = """\
// Q-X61 夹具：头部全量 + 2 CELL（行注释形态）
(DELAYFILE
  (SDFVERSION "3.0")
  (DESIGN "qx61_top")
  (DATE "Sat Nov  7 12:00:00 2026")
  (VENDOR "rfauto-fixture")
  (PROGRAM "qx61-writer")
  (VERSION "1.0.0")
  (DIVIDER /)
  (VOLTAGE 1.62:1.80:1.98)
  (PROCESS "typical")
  (TEMPERATURE -40:25:125)
  (TIMESCALE 1ns)
  (CELLDIVIDER |)
  /* 块注释：跨行，含 ( 括号 ) 与 "引号"
     不应影响配平与解析 */
  (CELL
    (CELLTYPE "DFF_X1")
    (INSTANCE u_core/u_ff1)
    (DELAY
      (ABSOLUTE
        (IOPATH (posedge CK) Q (0.100:0.120:0.150) (0.110:0.130:0.160))
        (COND D==1'b1 (IOPATH (posedge CK) QN (0.200:0.220:0.250) (0.210:0.230:0.260)))
        (INTERCONNECT u_core/u_ff1/Q u_core/u_and/A (0.010:0.012:0.015) (0.011:0.013:0.016))
      )
    )
    (TIMINGCHECK
      (SETUP D (posedge CK) (0.050:0.060:0.070))
      (HOLD D (posedge CK) (-0.010:0.005:0.020))
      (WIDTH (negedge CK) (0.300:0.350:0.400))
    )
  )
  (CELL
    (CELLTYPE "BUF_X2")
    (INSTANCE *)
    (DELAY
      (ABSOLUTE
        (PORT A (0.001::0.003))
      )
    )
  )
)
"""

_MINI_HEADER = '(SDFVERSION "3.0") (TIMESCALE 1ns)'

def _line_of(text: str, needle: str) -> int:
    """needle 首次出现所在行号（1 起）——行号断言不手写常量。"""
    return text[: text.index(needle)].count("\n") + 1

def _mini(body: str, header: str = _MINI_HEADER) -> dict[str, Any]:
    """小片段 SDF 文档（DELAYFILE 包裹 + 缺省头部）。"""
    return parse_sdf(f"(DELAYFILE {header}\n{body}\n)")

def _cell(doc: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return doc["cells"][index]

def _write(tmp_path: Path, text: str, name: str = "main.sdf") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)

@pytest.fixture(scope="module")
def main_doc() -> dict[str, Any]:
    return parse_sdf(SDF_MAIN)

# ══════════════════════════ S 表达式层 ══════════════════════════

class TestSexpr:
    def test_nested_lists_plain(self) -> None:
        forms = parse_sexpr("(a (b c) (d (e)))")
        assert len(forms) == 1
        assert sexpr_to_plain(forms[0]) == ["a", ["b", "c"], ["d", ["e"]]]

    def test_multiple_top_forms_and_bare_atom(self) -> None:
        forms = parse_sexpr("(a) b (c)")
        assert [sexpr_to_plain(f) for f in forms] == [["a"], "b", ["c"]]

    def test_quoted_string_atom(self) -> None:
        forms = parse_sexpr('(X "hello world" y)')
        atom = forms[0].items[1]
        assert isinstance(atom, SdfAtom)
        assert atom.quoted is True
        assert atom.text == "hello world"
        assert sexpr_to_plain(forms[0]) == ["X", '"hello world"', "y"]

    def test_quoted_string_escapes(self) -> None:
        # SDF 原文 ("a\"b\\c") → 内容 a"b\c
        atom = parse_sexpr('("a\\"b\\\\c")')[0].items[0]
        assert isinstance(atom, SdfAtom)
        assert atom.text == 'a"b\\c'

    def test_block_comment_multiline_line_numbers(self) -> None:
        forms = parse_sexpr("/* one\ntwo\nthree */ (x)\n(y)")
        assert [f.line for f in forms] == [3, 4]

    def test_block_comment_with_parens_and_quotes(self) -> None:
        forms = parse_sexpr('(a /* ( ) " */ b)')
        assert sexpr_to_plain(forms[0]) == ["a", "b"]

    def test_line_comment_swallows_to_eol(self) -> None:
        forms = parse_sexpr('(a // tail ( " \n b)')
        assert sexpr_to_plain(forms[0]) == ["a", "b"]

    def test_unterminated_block_comment_raises(self) -> None:
        with pytest.raises(SdfParseError, match="块注释"):
            parse_sexpr("(a /* never closed")

    def test_unterminated_string_raises(self) -> None:
        with pytest.raises(SdfParseError, match="引号"):
            parse_sexpr('(a "never closed)')

    def test_extra_close_paren_raises(self) -> None:
        with pytest.raises(SdfParseError, match="多余的右括号"):
            parse_sexpr("(a))")

    def test_unclosed_paren_raises_with_line(self) -> None:
        with pytest.raises(SdfParseError, match=r"第 2 行起.*缺 2 个右括号"):
            parse_sexpr("(a\n(b")

    def test_depth_guard_at_limit_ok(self) -> None:
        assert MAX_NEST_DEPTH == 512
        forms = parse_sexpr("(" * 512 + ")" * 512)
        depth = 0
        node: SdfAtom | SdfList = forms[0]
        while isinstance(node, SdfList):
            depth += 1
            if not node.items:
                break
            node = node.items[0]
        assert depth == 512

    def test_depth_guard_exceeded_raises(self) -> None:
        with pytest.raises(SdfParseError, match="嵌套深度超过上限 512"):
            parse_sexpr("(" * 513 + ")" * 513)

    def test_depth_guard_custom_limit(self) -> None:
        with pytest.raises(SdfParseError, match="上限 1"):
            parse_sexpr("((a))", max_depth=1)
        assert sexpr_to_plain(parse_sexpr("((a))", max_depth=2)[0]) == [["a"]]

    def test_escaped_chars_stay_in_atom_raw(self) -> None:
        # 转义的括号/空白不拆原子，反斜杠原文保留（标识符转义语义不解）
        forms = parse_sexpr("(a\\(b c\\ d)")
        assert sexpr_to_plain(forms[0]) == ["a\\(b", "c\\ d"]

    def test_slash_in_atom_vs_line_comment(self) -> None:
        forms = parse_sexpr("(u1/u2/Y a//c\n)")
        assert sexpr_to_plain(forms[0]) == ["u1/u2/Y", "a"]

    def test_crlf_line_endings(self) -> None:
        forms = parse_sexpr("(a\r\n b)\r\n(c)")
        assert [sexpr_to_plain(f) for f in forms] == [["a", "b"], ["c"]]
        first = forms[0]
        assert isinstance(first, SdfList)
        assert [item.line for item in first.items] == [1, 2]
        assert forms[1].line == 3

    def test_render_roundtrip_compact(self) -> None:
        form = parse_sexpr('(a  (b "q \\"s")   c)')[0]
        assert render_sexpr(form) == '(a (b "q \\"s") c)'
        assert render_sexpr(SdfAtom(text="x", line=1)) == "x"

    def test_parse_error_is_value_error(self) -> None:
        assert issubclass(SdfParseError, ValueError)

# ══════════════════════════ TIMESCALE 表驱动换算 ══════════════════════════

class TestTimescale:
    @pytest.mark.parametrize(("spec", "expected"), [
        ("1ns", 1e-9),
        ("10ns", 1e-8),
        ("100ns", 1e-7),
        ("1ps", 1e-12),
        ("10ps", 1e-11),
        ("100ps", 1e-10),
        ("1us", 1e-6),
        ("1fs", 1e-15),
        ("100fs", 1e-13),
        ("1ms", 1e-3),
        ("1s", 1.0),
    ])
    def test_known_factors(self, spec: str, expected: float) -> None:
        assert sdf_timescale_factor(spec) == expected

    def test_table_full_18_entries_independent_derivation(self) -> None:
        exponents = {"s": 0, "ms": -3, "us": -6, "ns": -9, "ps": -12, "fs": -15}
        expected = {
            f"{mult}{unit}": float(Decimal(mult).scaleb(exp))
            for unit, exp in exponents.items() for mult in (1, 10, 100)
        }
        assert len(TIMESCALE_FACTORS) == 18
        assert expected == TIMESCALE_FACTORS

    @pytest.mark.parametrize(("spec", "expected"), [
        ("100 ps", 1e-10),
        ("1.0ns", 1e-9),
        ("10.00 us", 1e-5),
        ("1NS", 1e-9),
        (" 1ns ", 1e-9),
    ])
    def test_lenient_spellings(self, spec: str, expected: float) -> None:
        assert sdf_timescale_factor(spec) == expected

    @pytest.mark.parametrize("spec", [
        "5ns", "1xs", "ns", "", "1", "1000ps", "0.1ns", "1 n s", "1µs",
    ])
    def test_fail_closed(self, spec: str) -> None:
        with pytest.raises(SdfParseError, match="fail-closed") as info:
            sdf_timescale_factor(spec)
        assert isinstance(info.value, ValueError)

    def test_parse_sdf_unknown_timescale_fail_closed(self) -> None:
        with pytest.raises(SdfParseError, match=r"第 1 行.*乘数 5"):
            parse_sdf('(DELAYFILE (SDFVERSION "3.0") (TIMESCALE 5ns))')

    def test_parse_sdf_nested_timescale_fail_closed(self) -> None:
        with pytest.raises(SdfParseError, match="TIMESCALE 形态非法"):
            parse_sdf('(DELAYFILE (SDFVERSION "3.0") (TIMESCALE (1ns)))')

    def test_default_timescale_when_absent(self) -> None:
        doc = _mini('(CELL (CELLTYPE "B") (INSTANCE b1) '
                    "(DELAY (ABSOLUTE (IOPATH A Y (2)))))",
                    header='(SDFVERSION "3.0")')
        ts = doc["header"]["timescale"]
        assert (ts["key"], ts["source"], ts["factor_s"]) == ("1ns", "default", 1e-9)
        assert any("缺 TIMESCALE" in w for w in doc["warnings"])
        assert _cell(doc)["delays"]["IOPATH"][0]["rise_triple"]["min_s"] == 2e-9

    def test_declared_100ps_scales_values(self) -> None:
        doc = _mini('(CELL (CELLTYPE "B") (INSTANCE b1) '
                    "(DELAY (ABSOLUTE (IOPATH A Y (1.5)))))",
                    header='(SDFVERSION "3.0") (TIMESCALE 100 ps)')
        assert doc["header"]["timescale"]["key"] == "100ps"
        triple = _cell(doc)["delays"]["IOPATH"][0]["rise_triple"]
        assert triple["min_s"] == 1.5e-10
        assert triple["min"] == 1.5

# ══════════════════════════ 三元组 ══════════════════════════

class TestTriple:
    def test_three_values_exact_seconds(self) -> None:
        t = parse_sdf_triple("1.234:2.5:3.678", 1e-9)
        assert t["form"] == "triple"
        assert (t["min"], t["typ"], t["max"]) == (1.234, 2.5, 3.678)
        assert (t["min_s"], t["typ_s"], t["max_s"]) == (1.234e-9, 2.5e-9, 3.678e-9)

    def test_single_value_fills_three_slots(self) -> None:
        t = parse_sdf_triple("1.2")
        assert t["form"] == "single"
        assert (t["min"], t["typ"], t["max"]) == (1.2, 1.2, 1.2)
        assert "min_s" not in t

    def test_empty_value_all_none(self) -> None:
        t = parse_sdf_triple("", 1e-9)
        assert t["form"] == "empty"
        assert [t[k] for k in ("min", "typ", "max", "min_s", "typ_s", "max_s")] \
            == [None] * 6

    @pytest.mark.parametrize(("text", "slots"), [
        ("1::3", (1.0, None, 3.0)),
        ("::3", (None, None, 3.0)),
        ("1::", (1.0, None, None)),
        (":2:", (None, 2.0, None)),
    ])
    def test_empty_slots_are_none(
        self, text: str, slots: tuple[float | None, ...]
    ) -> None:
        t = parse_sdf_triple(text, 1e-9)
        assert t["form"] == "triple"
        assert (t["min"], t["typ"], t["max"]) == slots
        assert all((t[f"{k}_s"] is None) == (v is None)
                   for k, v in zip(("min", "typ", "max"), slots, strict=True))

    def test_negative_values(self) -> None:
        t = parse_sdf_triple("-0.010:0.005:0.020", 1e-9)
        assert (t["min_s"], t["typ_s"], t["max_s"]) == (-1e-11, 5e-12, 2e-11)

    def test_spaced_triple_compacted(self) -> None:
        t = parse_sdf_triple(" 1 : 2 : 3 ")
        assert t["raw"] == "1:2:3"
        assert (t["form"], t["min"], t["typ"], t["max"]) == ("triple", 1.0, 2.0, 3.0)

    @pytest.mark.parametrize("text", ["1:2", "abc", "1:2:3:4", "1:x:3", "nan"])
    def test_invalid_forms(self, text: str) -> None:
        t = parse_sdf_triple(text, 1e-9)
        assert t["form"] == "invalid"
        assert (t["min"], t["typ"], t["max"], t["max_s"]) == (None, None, None, None)

    def test_scientific_and_signed_numbers(self) -> None:
        t = parse_sdf_triple("+1e-3:.5:2.")
        assert (t["min"], t["typ"], t["max"]) == (0.001, 0.5, 2.0)

    def test_decimal_scaling_beats_naive_float(self) -> None:
        # 朴素 float 乘法不落在最近 double 上——Decimal 精确缩放单次舍入
        assert 0.1 * 1e-9 != 1e-10
        assert parse_sdf_triple("0.100", 1e-9)["min_s"] == 1e-10

# ══════════════════════════ 头部 ══════════════════════════

class TestHeader:
    def test_header_closed_set_pin(self) -> None:
        assert HEADER_KEYWORDS == (
            "SDFVERSION", "DESIGN", "DATE", "VENDOR", "PROGRAM", "VERSION",
            "DIVIDER", "VOLTAGE", "PROCESS", "TEMPERATURE", "TIMESCALE")

    def test_header_strings(self, main_doc: dict[str, Any]) -> None:
        h = main_doc["header"]
        assert h["sdf_version"] == "3.0"
        assert h["design"] == "qx61_top"
        assert h["date"] == "Sat Nov  7 12:00:00 2026"
        assert h["vendor"] == "rfauto-fixture"
        assert h["program"] == "qx61-writer"
        assert h["version"] == "1.0.0"
        assert h["process"] == "typical"

    def test_header_divider_declared(self, main_doc: dict[str, Any]) -> None:
        h = main_doc["header"]
        assert (h["divider"], h["divider_source"]) == ("/", "declared")

    def test_voltage_temperature_triples_unscaled(
        self, main_doc: dict[str, Any]
    ) -> None:
        v = main_doc["header"]["voltage"]
        t = main_doc["header"]["temperature"]
        assert (v["form"], v["min"], v["typ"], v["max"]) == ("triple", 1.62, 1.8, 1.98)
        assert (t["min"], t["typ"], t["max"]) == (-40.0, 25.0, 125.0)
        assert "min_s" not in v and "min_s" not in t

    def test_timescale_entry(self, main_doc: dict[str, Any]) -> None:
        assert main_doc["header"]["timescale"] == {
            "raw": "1ns", "key": "1ns", "multiplier": 1, "unit": "ns",
            "factor_s": 1e-9, "source": "declared",
        }

    def test_unknown_header_key_kept_with_warning(
        self, main_doc: dict[str, Any]
    ) -> None:
        line = _line_of(SDF_MAIN, "(CELLDIVIDER")
        assert main_doc["header"]["unknown"] == [
            {"keyword": "CELLDIVIDER", "line": line, "raw": "(CELLDIVIDER |)"}]
        assert main_doc["warnings"] == [
            f"第 {line} 行：未知头部键 CELLDIVIDER（非 IEEE 1497 头部键闭集）"
            "——原文保留于 header.unknown"]
        assert main_doc["stats"]["n_unknown_header"] == 1

    def test_schema_and_celltypes(self, main_doc: dict[str, Any]) -> None:
        assert main_doc["schema"] == "sdf/1.0"
        assert main_doc["celltypes"] == ["DFF_X1", "BUF_X2"]

    def test_missing_delayfile_raises(self) -> None:
        with pytest.raises(SdfParseError, match="缺 DELAYFILE 头"):
            parse_sdf('(CELL (CELLTYPE "X"))')

    @pytest.mark.parametrize("text", ["", "   \n", "/* only */ // c\n"])
    def test_empty_or_comment_only_raises(self, text: str) -> None:
        with pytest.raises(SdfParseError, match="空文本"):
            parse_sdf(text)

    def test_duplicate_header_key_last_wins(self) -> None:
        doc = _mini("", header='(SDFVERSION "3.0") (DESIGN "a") (DESIGN "b")')
        assert doc["header"]["design"] == "b"
        assert any("头部键 DESIGN 重复" in w for w in doc["warnings"])

    def test_missing_sdfversion_warns(self) -> None:
        doc = _mini("", header="(TIMESCALE 1ns)")
        assert doc["header"]["sdf_version"] is None
        assert any("缺 SDFVERSION" in w for w in doc["warnings"])

    def test_header_after_cell_warns_but_applies(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1))\n(DESIGN "late")')
        assert doc["header"]["design"] == "late"
        assert any("出现在 CELL 之后" in w for w in doc["warnings"])

    def test_bom_prefix_stripped(self) -> None:
        doc = parse_sdf("\ufeff" + SDF_MAIN)
        assert doc["header"]["design"] == "qx61_top"

    def test_nonstandard_divider_adopted_with_warning(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE a|b))',
                    header='(SDFVERSION "3.0") (TIMESCALE 1ns) (DIVIDER |)')
        assert doc["header"]["divider"] == "|"
        assert _cell(doc)["instance_path"] == ["a", "b"]
        assert any("DIVIDER '|'" in w for w in doc["warnings"])

    def test_trailing_top_forms_ignored_with_warning(self) -> None:
        doc = parse_sdf(f"(DELAYFILE {_MINI_HEADER})\n(extra)")
        assert doc["cells"] == []
        assert any("之后另有 1 个" in w for w in doc["warnings"])

    def test_default_divider_dot_and_escaped_divider(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE top.u1\\.x.u2))')
        assert doc["header"]["divider"] == "."
        assert doc["header"]["divider_source"] == "default"
        assert _cell(doc)["instance_path"] == ["top", "u1\\.x", "u2"]

# ══════════════════════════ CELL 段（主夹具逐类）══════════════════════════

class TestCellsMain:
    def test_two_cells_index_and_line(self, main_doc: dict[str, Any]) -> None:
        cells = main_doc["cells"]
        assert [c["index"] for c in cells] == [0, 1]
        assert cells[0]["line"] == _line_of(SDF_MAIN, '(CELLTYPE "DFF_X1")') - 1
        assert cells[1]["line"] == _line_of(SDF_MAIN, '(CELLTYPE "BUF_X2")') - 1

    def test_cell1_instance_hierarchy(self, main_doc: dict[str, Any]) -> None:
        cell = _cell(main_doc)
        assert cell["celltype"] == "DFF_X1"
        assert cell["instance"] == "u_core/u_ff1"
        assert cell["instance_wildcard"] is False
        assert cell["instance_path"] == ["u_core", "u_ff1"]

    def test_delays_dict_has_all_19_buckets(self, main_doc: dict[str, Any]) -> None:
        keys = list(_cell(main_doc)["delays"])
        assert keys == [*DELAY_KINDS, *TIMING_CHECK_KINDS]
        assert len(keys) == 19

    def test_iopath_edge_and_rise_fall(self, main_doc: dict[str, Any]) -> None:
        io = _cell(main_doc)["delays"]["IOPATH"][0]
        assert (io["kind"], io["section"], io["mode"]) == ("IOPATH", "DELAY", "absolute")
        assert (io["from_pin"], io["from_edge"], io["to_pin"]) == ("CK", "posedge", "Q")
        assert (io["cond"], io["cond_name"], io["condelse"]) == (None, None, False)
        assert io["n_triples"] == 2
        rise, fall = io["rise_triple"], io["fall_triple"]
        assert (rise["min_s"], rise["typ_s"], rise["max_s"]) == (1e-10, 1.2e-10, 1.5e-10)
        assert (fall["min_s"], fall["typ_s"], fall["max_s"]) == (1.1e-10, 1.3e-10, 1.6e-10)
        assert rise["raw"] == "0.100:0.120:0.150"
        assert io["fall_inherited"] is False
        assert (io["retain"], io["pulse_limits"]) == ([], [])
        assert io["line"] == _line_of(SDF_MAIN, "(IOPATH (posedge CK) Q ")

    def test_iopath_cond_carried_not_evaluated(self, main_doc: dict[str, Any]) -> None:
        io = _cell(main_doc)["delays"]["IOPATH"][1]
        assert io["cond"] == "D==1'b1"
        assert io["cond_name"] is None
        assert (io["from_pin"], io["to_pin"]) == ("CK", "QN")
        assert io["rise_triple"]["max_s"] == 2.5e-10
        assert io["fall_triple"]["min_s"] == 2.1e-10

    def test_interconnect(self, main_doc: dict[str, Any]) -> None:
        ic = _cell(main_doc)["delays"]["INTERCONNECT"]
        assert len(ic) == 1
        assert (ic[0]["from_pin"], ic[0]["to_pin"]) == (
            "u_core/u_ff1/Q", "u_core/u_and/A")
        assert ic[0]["rise_triple"]["min_s"] == 1e-11
        assert ic[0]["fall_triple"]["max_s"] == 1.6e-11

    def test_setup_check(self, main_doc: dict[str, Any]) -> None:
        (setup,) = _cell(main_doc)["delays"]["SETUP"]
        assert (setup["section"], setup["check_type"]) == ("TIMINGCHECK", "SETUP")
        assert (setup["pin"], setup["edge"]) == ("D", None)
        assert (setup["ref_pin"], setup["ref_edge"]) == ("CK", "posedge")
        assert setup["n_triples"] == 1
        assert setup["triples"][0]["max_s"] == 7e-11
        assert setup["cond"] is None

    def test_hold_check_negative_min(self, main_doc: dict[str, Any]) -> None:
        (hold,) = _cell(main_doc)["delays"]["HOLD"]
        t = hold["triples"][0]
        assert (t["min_s"], t["typ_s"], t["max_s"]) == (-1e-11, 5e-12, 2e-11)

    def test_width_single_port(self, main_doc: dict[str, Any]) -> None:
        (width,) = _cell(main_doc)["delays"]["WIDTH"]
        assert (width["pin"], width["edge"]) == ("CK", "negedge")
        assert (width["ref_pin"], width["ref_edge"]) == (None, None)
        t = width["triples"][0]
        assert (t["min"], t["typ"], t["max"]) == (0.3, 0.35, 0.4)
        assert t["max_s"] == 4e-10

    def test_cell2_wildcard_instance(self, main_doc: dict[str, Any]) -> None:
        cell = _cell(main_doc, 1)
        assert (cell["celltype"], cell["instance"]) == ("BUF_X2", "*")
        assert cell["instance_wildcard"] is True
        assert cell["instance_path"] == ["*"]

    def test_port_empty_slot_triple(self, main_doc: dict[str, Any]) -> None:
        (port,) = _cell(main_doc, 1)["delays"]["PORT"]
        assert port["pin"] == "A"
        rise = port["rise_triple"]
        assert (rise["form"], rise["min"], rise["typ"], rise["max"]) == (
            "triple", 0.001, None, 0.003)
        assert (rise["min_s"], rise["typ_s"], rise["max_s"]) == (1e-12, None, 3e-12)
        assert port["fall_inherited"] is True
        assert port["fall_triple"] == rise

    def test_main_stats(self, main_doc: dict[str, Any]) -> None:
        s = main_doc["stats"]
        assert (s["n_cells"], s["n_top_cells"], s["n_wildcard_cells"]) == (2, 0, 1)
        assert (s["n_delay_entries"], s["n_timing_checks"]) == (4, 3)
        assert (s["n_cond_entries"], s["n_absolute"], s["n_increment"]) == (1, 4, 0)
        assert s["n_unsupported"] == 0
        assert {k: v for k, v in s["by_kind"].items() if v} == {
            "IOPATH": 2, "INTERCONNECT": 1, "PORT": 1,
            "SETUP": 1, "HOLD": 1, "WIDTH": 1}
        assert s["n_warnings"] == len(main_doc["warnings"]) == 1

    def test_parse_deterministic_and_json_native(self) -> None:
        a = json.dumps(parse_sdf(SDF_MAIN), sort_keys=True, allow_nan=False)
        b = json.dumps(parse_sdf(SDF_MAIN), sort_keys=True, allow_nan=False)
        assert a == b

# ══════════════════════════ CELL 段（变体片段）══════════════════════════

class TestCellVariants:
    def test_top_level_empty_instance(self) -> None:
        doc = _mini('(CELL (CELLTYPE "TOP") (INSTANCE) '
                    "(DELAY (ABSOLUTE (INTERCONNECT a/Y b/A (1)))))")
        cell = _cell(doc)
        assert (cell["instance"], cell["instance_wildcard"], cell["instance_path"]) \
            == (None, False, None)
        assert doc["stats"]["n_top_cells"] == 1

    def test_missing_instance_clause_warns(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X"))')
        assert _cell(doc)["instance"] is None
        assert any("缺 INSTANCE 子句" in w for w in doc["warnings"])

    def test_double_star_wildcard_nonstandard_warns(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE **))')
        cell = _cell(doc)
        assert (cell["instance"], cell["instance_wildcard"]) == ("**", True)
        assert any("'**'" in w and "通配" in w for w in doc["warnings"])

    def test_quoted_instance_adopted_with_warning(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE "u1"))')
        assert _cell(doc)["instance"] == "u1"
        assert any("INSTANCE 名带引号" in w for w in doc["warnings"])

    def test_increment_and_incremental_spelling(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (DELAY '
                    "(INCREMENT (IOPATH A Y (1))) (INCREMENTAL (IOPATH B Y (2)))))")
        modes = [e["mode"] for e in _cell(doc)["delays"]["IOPATH"]]
        assert modes == ["increment", "increment"]
        assert (doc["stats"]["n_increment"], doc["stats"]["n_absolute"]) == (2, 0)

    def test_single_delval_fall_inherits_rise(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (IOPATH A Y (1:2:3)))))")
        io = _cell(doc)["delays"]["IOPATH"][0]
        assert io["fall_inherited"] is True
        assert io["fall_triple"] == io["rise_triple"]
        assert io["rise_triple"]["max_s"] == 3e-9

    def test_six_delvals_standard_no_count_warning(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (IOPATH A Y (1) (2) (3) (4) (5) (6)))))")
        io = _cell(doc)["delays"]["IOPATH"][0]
        assert io["n_triples"] == 6
        assert (io["rise_triple"]["min"], io["fall_triple"]["min"]) == (1.0, 2.0)
        assert not any("合法档" in w for w in doc["warnings"])

    def test_four_delvals_nonstandard_warns(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (IOPATH A Y (1) (2) (3) (4)))))")
        assert _cell(doc)["delays"]["IOPATH"][0]["n_triples"] == 4
        assert any("非 IEEE 1497 合法档" in w for w in doc["warnings"])

    def test_retain_captured(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (DELAY (ABSOLUTE '
                    "(IOPATH A Y (RETAIN (0.1:0.2:0.3)) (1:2:3) (4:5:6)))))")
        io = _cell(doc)["delays"]["IOPATH"][0]
        assert io["n_triples"] == 2
        assert len(io["retain"]) == 1
        assert io["retain"][0]["min_s"] == 1e-10

    def test_pulse_limits_compound_delval(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (DELAY (ABSOLUTE '
                    "(IOPATH A Y ((1:2:3) (0.5) (0.6)) ((4:5:6))))))")
        io = _cell(doc)["delays"]["IOPATH"][0]
        assert [t["min"] for t in io["triples"]] == [1.0, 4.0]
        assert len(io["pulse_limits"]) == 1
        pulse = io["pulse_limits"][0]
        assert pulse["index"] == 0
        assert pulse["reject"]["typ_s"] == 5e-10
        assert pulse["error"]["max_s"] == 6e-10

    def test_condelse(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (CONDELSE (IOPATH A Y (1))))))")
        io = _cell(doc)["delays"]["IOPATH"][0]
        assert (io["condelse"], io["cond"]) == (True, None)
        assert doc["stats"]["n_cond_entries"] == 1

    def test_cond_named_with_parenthesized_expr(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (DELAY (ABSOLUTE '
                    "(COND \"sel_hi\" (S==1'b1) && (E==1'b0) (IOPATH A Y (1) (2))))))")
        io = _cell(doc)["delays"]["IOPATH"][0]
        assert io["cond"] == "(S==1'b1) && (E==1'b0)"
        assert io["cond_name"] == "sel_hi"

    def test_cond_without_target_unsupported(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (COND A B))))")
        cell = _cell(doc)
        assert cell["delays"]["IOPATH"] == []
        assert cell["unsupported"][0]["keyword"] == "COND"
        assert cell["unsupported"][0]["raw"] == "(COND A B)"
        assert any("COND 缺被包裹" in w for w in doc["warnings"])

    def test_setuphold_with_scond_ccond(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (TIMINGCHECK '
                    "(SETUPHOLD D (posedge CK) (1) (2) (SCOND \"s1\" EN==1'b1) "
                    "(CCOND RST==1'b0))))")
        (sh,) = _cell(doc)["delays"]["SETUPHOLD"]
        assert [t["min"] for t in sh["triples"]] == [1.0, 2.0]
        assert (sh["scond"], sh["scond_name"]) == ("EN==1'b1", "s1")
        assert (sh["ccond"], sh["ccond_name"]) == ("RST==1'b0", None)
        assert not any("参数" in w for w in doc["warnings"])

    def test_timing_check_port_cond(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (TIMINGCHECK '
                    "(SETUP D (COND EN (posedge CK)) (1))))")
        (setup,) = _cell(doc)["delays"]["SETUP"]
        assert (setup["ref_pin"], setup["ref_edge"]) == ("CK", "posedge")
        assert setup["ports"][1]["cond"] == "EN"
        assert setup["cond"] == "EN"

    def test_all_timing_check_arities(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (TIMINGCHECK '
                    "(RECOVERY (posedge RN) (posedge CK) (1)) "
                    "(REMOVAL (posedge RN) (posedge CK) (2)) "
                    "(RECREM (posedge RN) (posedge CK) (1) (2)) "
                    "(SKEW CK1 CK2 (3)) (TIMESKEW CK1 CK2 (3)) "
                    "(FULLSKEW CK1 CK2 (3) (4)) (PERIOD CK (10)) "
                    "(NOCHANGE D (posedge CK) (1) (2))))")
        delays = _cell(doc)["delays"]
        for kind in ("RECOVERY", "REMOVAL", "RECREM", "SKEW", "TIMESKEW",
                     "FULLSKEW", "PERIOD", "NOCHANGE"):
            assert len(delays[kind]) == 1, kind
        assert delays["RECREM"][0]["n_triples"] == 2
        assert delays["FULLSKEW"][0]["n_triples"] == 2
        assert (delays["PERIOD"][0]["pin"], delays["PERIOD"][0]["ref_pin"]) == ("CK", None)
        assert doc["warnings"] == []

    def test_timing_check_param_count_mismatch_warns(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(TIMINGCHECK (SETUP D CK (1) (2))))")
        assert _cell(doc)["delays"]["SETUP"][0]["n_triples"] == 2
        assert any("期望 3" in w for w in doc["warnings"])

    def test_unknown_timing_check_unsupported(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(TIMINGCHECK (PULSEWIDTH CK (1))))")
        cell = _cell(doc)
        assert cell["unsupported"][0]["keyword"] == "PULSEWIDTH"
        assert sum(len(cell["delays"][k]) for k in TIMING_CHECK_KINDS) == 0
        assert any("PULSEWIDTH" in w for w in doc["warnings"])

    def test_timingenv_and_label_kept_raw(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(TIMINGENV (ARRIVAL (posedge CK) D (1) (2) (3) (4))) "
                    "(LABEL (ABSOLUTE (T1 (5)))))")
        unsupported = _cell(doc)["unsupported"]
        assert [u["keyword"] for u in unsupported] == ["TIMINGENV", "LABEL"]
        assert unsupported[1]["raw"] == "(LABEL (ABSOLUTE (T1 (5))))"
        assert doc["stats"]["n_unsupported"] == 2

    def test_pathpulse_time_vs_percent(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (DELAY '
                    "(PATHPULSE A Y (13) (21)) (PATHPULSEPERCENT A Y (25) (35))))",
                    header='(SDFVERSION "3.0") (TIMESCALE 1ps)')
        delays = _cell(doc)["delays"]
        (pp,) = delays["PATHPULSE"]
        assert (pp["from_pin"], pp["to_pin"], pp["unit"]) == ("A", "Y", "time")
        assert (pp["reject"]["min_s"], pp["error"]["min_s"]) == (1.3e-11, 2.1e-11)
        (ppp,) = delays["PATHPULSEPERCENT"]
        assert ppp["unit"] == "percent"
        assert ppp["reject"]["min"] == 25.0
        assert "min_s" not in ppp["reject"]

    def test_netdelay_and_device(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (DELAY (ABSOLUTE '
                    "(NETDELAY n1 (1)) (DEVICE (2)) (DEVICE Y (3)))))")
        delays = _cell(doc)["delays"]
        assert delays["NETDELAY"][0]["net"] == "n1"
        assert [d["pin"] for d in delays["DEVICE"]] == [None, "Y"]
        assert delays["DEVICE"][1]["rise_triple"]["min_s"] == 3e-9

    def test_unknown_del_def_unsupported(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (FOO A (1)))))")
        assert _cell(doc)["unsupported"][0]["keyword"] == "FOO"
        assert any("'FOO'" in w for w in doc["warnings"])

    def test_invalid_value_warns_and_none(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (IOPATH A Y (1:2)))))")
        rise = _cell(doc)["delays"]["IOPATH"][0]["rise_triple"]
        assert (rise["form"], rise["min"], rise["max_s"]) == ("invalid", None, None)
        assert any("'1:2' 非法" in w for w in doc["warnings"])

    def test_bare_value_atom_parsed_with_warning(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (IOPATH A Y 1:2:3))))")
        rise = _cell(doc)["delays"]["IOPATH"][0]["rise_triple"]
        assert (rise["min"], rise["max"]) == (1.0, 3.0)
        assert any("未加括号" in w for w in doc["warnings"])

    def test_edge_identifiers_lowercased(self) -> None:
        assert {"posedge", "negedge", "01", "10", "0z", "z1", "1z", "z0"} \
            == EDGE_IDENTIFIERS
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) (DELAY (ABSOLUTE '
                    "(IOPATH (01 A) Y (1)) (IOPATH (Z1 B) Y (1)) "
                    "(IOPATH (POSEDGE C) Y (1)))))")
        edges = [e["from_edge"] for e in _cell(doc)["delays"]["IOPATH"]]
        assert edges == ["01", "z1", "posedge"]

    def test_bus_port_names_kept_verbatim(self) -> None:
        doc = _mini('(CELL (CELLTYPE "X") (INSTANCE x1) '
                    "(DELAY (ABSOLUTE (IOPATH D[3] Q[3] (1)))))")
        io = _cell(doc)["delays"]["IOPATH"][0]
        assert (io["from_pin"], io["to_pin"]) == ("D[3]", "Q[3]")

    def test_keywords_case_insensitive(self) -> None:
        doc = parse_sdf('(delayfile (sdfversion "3.0") (timescale 1ns) '
                        '(cell (celltype "X") (instance x1) '
                        "(delay (absolute (iopath A Y (1))))))")
        assert doc["header"]["sdf_version"] == "3.0"
        assert len(_cell(doc)["delays"]["IOPATH"]) == 1

    def test_warnings_sorted_by_line(self) -> None:
        doc = parse_sdf('(DELAYFILE\n(SDFVERSION "3.0")\n'
                        '(CELL (CELLTYPE "A") (INSTANCE **))\n'
                        '(DESIGN "late")\n(DIVIDER |)\n)')
        lines = [int(re.match(r"第 (\d+) 行", w).group(1))  # type: ignore[union-attr]
                 for w in doc["warnings"]]
        assert lines == sorted(lines)
        assert lines[0] == 1 and len(lines) == 5

# ══════════════════════════ 查询三函数 ══════════════════════════

_LOOKUP_BODY = """\
(CELL (CELLTYPE "BUF_X2") (INSTANCE u1) (DELAY (ABSOLUTE (IOPATH A Z (1)))))
(CELL (CELLTYPE "BUF_X2") (INSTANCE *) (DELAY (ABSOLUTE (IOPATH A Z (2)))))
(CELL (CELLTYPE "BUF_X2") (INSTANCE u2) (DELAY (ABSOLUTE (IOPATH A Z (3)))))
(CELL (CELLTYPE "BUF_X2") (INSTANCE) (DELAY (ABSOLUTE (IOPATH A Z (4)))))
(CELL (CELLTYPE "INV") (INSTANCE u1) (DELAY (ABSOLUTE (IOPATH A ZN (5)))))
"""

@pytest.fixture(scope="module")
def lookup_doc() -> dict[str, Any]:
    return _mini(_LOOKUP_BODY)

def _pairs(matches: list[dict[str, Any]]) -> list[tuple[int, str]]:
    return [(m["index"], m["match"]) for m in matches]

class TestQueries:
    def test_lookup_exact_plus_wildcard(self, lookup_doc: dict[str, Any]) -> None:
        assert _pairs(sdf_cell_lookup(lookup_doc, "BUF_X2", "u1")) == [
            (0, "exact"), (1, "wildcard")]

    def test_lookup_top_level_only(self, lookup_doc: dict[str, Any]) -> None:
        assert _pairs(sdf_cell_lookup(lookup_doc, "BUF_X2")) == [(3, "top")]

    def test_lookup_star_only_wildcard(self, lookup_doc: dict[str, Any]) -> None:
        assert _pairs(sdf_cell_lookup(lookup_doc, "BUF_X2", "*")) == [(1, "wildcard")]

    def test_lookup_unmatched_instance_only_wildcard(
        self, lookup_doc: dict[str, Any]
    ) -> None:
        assert _pairs(sdf_cell_lookup(lookup_doc, "BUF_X2", "u9")) == [(1, "wildcard")]
        assert _pairs(sdf_cell_lookup(lookup_doc, "INV", "u1")) == [(4, "exact")]

    def test_lookup_unknown_celltype_empty(self, lookup_doc: dict[str, Any]) -> None:
        assert sdf_cell_lookup(lookup_doc, "NOPE") == []
        assert sdf_cell_lookup(lookup_doc, "INV") == []

    def test_lookup_does_not_mutate_doc(self, lookup_doc: dict[str, Any]) -> None:
        hits = sdf_cell_lookup(lookup_doc, "BUF_X2", "u1")
        assert hits[0]["delays"] is lookup_doc["cells"][0]["delays"]
        assert all("match" not in cell for cell in lookup_doc["cells"])

    def test_lookup_main_fixture(self, main_doc: dict[str, Any]) -> None:
        assert _pairs(sdf_cell_lookup(main_doc, "DFF_X1", "u_core/u_ff1")) == [
            (0, "exact")]
        assert _pairs(sdf_cell_lookup(main_doc, "BUF_X2", "any/inst")) == [
            (1, "wildcard")]
        assert sdf_cell_lookup(main_doc, "DFF_X1") == []

    def test_delay_paths_main(self, main_doc: dict[str, Any]) -> None:
        rows = sdf_delay_paths(main_doc, "DFF_X1")
        assert [r["kind"] for r in rows] == ["IOPATH", "IOPATH", "INTERCONNECT"]
        assert [r["to_pin"] for r in rows] == ["Q", "QN", "u_core/u_and/A"]
        assert rows[0]["rise_s"] == {"min": 1e-10, "typ": 1.2e-10, "max": 1.5e-10}
        assert rows[0]["fall_s"] == {"min": 1.1e-10, "typ": 1.3e-10, "max": 1.6e-10}
        assert rows[1]["cond"] == "D==1'b1"
        assert rows[2]["from_edge"] is None
        assert {r["instance"] for r in rows} == {"u_core/u_ff1"}

    def test_delay_paths_sorted_stable(self) -> None:
        doc = _mini('(CELL (CELLTYPE "MUX2") (INSTANCE m1) (DELAY (ABSOLUTE '
                    "(IOPATH S Z (5)) (COND S==1'b0 (IOPATH A Z (3))) "
                    "(IOPATH B Z (4)) (COND S==1'b1 (IOPATH A Z (2))))))",
                    header='(SDFVERSION "3.0") (TIMESCALE 1ps)')
        rows = sdf_delay_paths(doc, "MUX2")
        assert [(r["from_pin"], r["cond"]) for r in rows] == [
            ("A", "S==1'b0"), ("A", "S==1'b1"), ("B", None), ("S", None)]
        assert [r["rise_s"]["min"] for r in rows] == [3e-12, 2e-12, 4e-12, 5e-12]
        assert sdf_delay_paths(doc, "MUX2") == rows

    def test_delay_paths_grouped_by_cell_order(self, lookup_doc: dict[str, Any]) -> None:
        rows = sdf_delay_paths(lookup_doc, "BUF_X2")
        assert [(r["cell_index"], r["instance"]) for r in rows] == [
            (0, "u1"), (1, "*"), (2, "u2"), (3, None)]
        assert rows[1]["instance_wildcard"] is True
        assert all(r["fall_inherited"] for r in rows)

    def test_delay_paths_unknown_celltype_empty(self, main_doc: dict[str, Any]) -> None:
        assert sdf_delay_paths(main_doc, "NOPE") == []
        assert sdf_delay_paths(main_doc, "BUF_X2") == []  # PORT 不入平坦清单

    def test_timing_check_summary_main(self, main_doc: dict[str, Any]) -> None:
        summary = sdf_timing_check_summary(main_doc)
        assert summary["n_timing_checks"] == 3
        assert summary["types_present"] == ["SETUP", "HOLD", "WIDTH"]
        assert list(summary["by_type"]) == list(TIMING_CHECK_KINDS)
        setup = summary["by_type"]["SETUP"]
        assert (setup["count"], setup["worst_max_s"], setup["worst_max"]) == (1, 7e-11, 0.07)
        assert setup["worst_at"] == {
            "cell_index": 0, "celltype": "DFF_X1", "instance": "u_core/u_ff1",
            "pin": "D", "ref_pin": "CK", "triple_index": 0,
            "line": _line_of(SDF_MAIN, "(SETUP D"),
        }
        assert summary["by_type"]["HOLD"]["worst_max_s"] == 2e-11
        assert summary["by_type"]["WIDTH"]["worst_max_s"] == 4e-10
        assert summary["by_type"]["WIDTH"]["worst_at"]["ref_pin"] is None
        recovery = summary["by_type"]["RECOVERY"]
        assert (recovery["count"], recovery["worst_max_s"], recovery["worst_at"]) == (
            0, None, None)

    def test_timing_check_summary_tie_and_multi_value(self) -> None:
        doc = _mini('(CELL (CELLTYPE "F") (INSTANCE a) (TIMINGCHECK '
                    "(SETUP D CK (2)) (SETUPHOLD D CK (1) (5))))\n"
                    '(CELL (CELLTYPE "F") (INSTANCE b) (TIMINGCHECK (SETUP D CK (2))))')
        by_type = sdf_timing_check_summary(doc)["by_type"]
        assert by_type["SETUP"]["count"] == 2
        assert by_type["SETUP"]["worst_max_s"] == 2e-9
        assert by_type["SETUP"]["worst_at"]["cell_index"] == 0  # 并列取文档序首个
        assert by_type["SETUPHOLD"]["worst_max_s"] == 5e-9
        assert by_type["SETUPHOLD"]["worst_at"]["triple_index"] == 1

    def test_timing_check_summary_skips_none_max(self) -> None:
        doc = _mini('(CELL (CELLTYPE "F") (INSTANCE a) '
                    "(TIMINGCHECK (SETUP D CK (1:2:))))")
        setup = sdf_timing_check_summary(doc)["by_type"]["SETUP"]
        assert (setup["count"], setup["worst_max_s"], setup["worst_at"]) == (1, None, None)

    def test_celltype_summary(self, main_doc: dict[str, Any]) -> None:
        assert sdf_celltype_summary(main_doc) == [
            {"celltype": "DFF_X1", "n_cells": 1, "n_top": 0, "n_wildcard": 0,
             "n_instances": 1, "n_delay_entries": 3, "n_timing_checks": 3},
            {"celltype": "BUF_X2", "n_cells": 1, "n_top": 0, "n_wildcard": 1,
             "n_instances": 0, "n_delay_entries": 1, "n_timing_checks": 0},
        ]

# ══════════════════════════ 服务信封 ══════════════════════════

class TestService:
    def test_parse_file_ok_envelope(self, tmp_path: Path) -> None:
        result = sdf_service.parse_sdf_file(_write(tmp_path, SDF_MAIN))
        assert result["ok"] is True
        assert set(result) == {"ok", "path", "schema", "header", "cells",
                               "celltypes", "stats", "warnings"}
        assert result["stats"]["n_cells"] == 2
        assert result["header"]["timescale"]["factor_s"] == 1e-9

    def test_parse_file_missing(self, tmp_path: Path) -> None:
        result = sdf_service.parse_sdf_file(tmp_path / "no.sdf")
        assert result["ok"] is False
        assert "不存在" in result["errors"][0]

    @pytest.mark.parametrize("text", ["", "  \n\t"])
    def test_parse_file_empty(self, tmp_path: Path, text: str) -> None:
        result = sdf_service.parse_sdf_file(_write(tmp_path, text))
        assert result["ok"] is False
        assert "为空" in result["errors"][0]

    def test_parse_file_no_delayfile(self, tmp_path: Path) -> None:
        result = sdf_service.parse_sdf_file(_write(tmp_path, '(CELL (CELLTYPE "X"))'))
        assert result["ok"] is False
        assert "DELAYFILE" in result["errors"][0]

    def test_parse_file_unknown_timescale(self, tmp_path: Path) -> None:
        text = SDF_MAIN.replace("(TIMESCALE 1ns)", "(TIMESCALE 1xs)")
        result = sdf_service.parse_sdf_file(_write(tmp_path, text))
        assert result["ok"] is False
        assert "fail-closed" in result["errors"][0]

    def test_parse_file_bom_and_latin1(self, tmp_path: Path) -> None:
        bom = tmp_path / "bom.sdf"
        bom.write_bytes(b"\xef\xbb\xbf" + SDF_MAIN.encode("utf-8"))
        assert sdf_service.parse_sdf_file(bom)["ok"] is True
        latin = tmp_path / "latin.sdf"
        ascii_doc = f'(DELAYFILE {_MINI_HEADER} (DESIGN "lat"))'.encode("ascii")
        latin.write_bytes(b"/* caf\xe9 */ " + ascii_doc)
        result = sdf_service.parse_sdf_file(latin)
        assert result["ok"] is True
        assert result["header"]["design"] == "lat"

    def test_parse_file_directory_unreadable(self, tmp_path: Path) -> None:
        result = sdf_service.parse_sdf_file(tmp_path)
        assert result["ok"] is False
        assert "不可读" in result["errors"][0]

    def test_report_envelope(self, tmp_path: Path) -> None:
        result = sdf_service.sdf_report(_write(tmp_path, SDF_MAIN))
        assert result["ok"] is True
        assert "cells" not in result
        assert [r["celltype"] for r in result["celltype_counts"]] == ["DFF_X1", "BUF_X2"]
        summary = result["timing_check_summary"]
        assert summary["n_timing_checks"] == 3
        assert summary["by_type"]["SETUP"]["worst_max_s"] == 7e-11

    def test_cell_detail_exact(self, tmp_path: Path) -> None:
        result = sdf_service.sdf_cell_detail(
            _write(tmp_path, SDF_MAIN), "DFF_X1", "u_core/u_ff1")
        assert result["ok"] is True
        assert (result["n_matches"], result["matches"][0]["match"]) == (1, "exact")
        assert len(result["delay_paths"]) == 3

    def test_cell_detail_wildcard_hit(self, tmp_path: Path) -> None:
        result = sdf_service.sdf_cell_detail(
            _write(tmp_path, SDF_MAIN), "BUF_X2", "u_any")
        assert result["ok"] is True
        assert [m["match"] for m in result["matches"]] == ["wildcard"]
        assert result["delay_paths"] == []

    def test_cell_detail_unknown_celltype(self, tmp_path: Path) -> None:
        result = sdf_service.sdf_cell_detail(_write(tmp_path, SDF_MAIN), "NAND9")
        assert result["ok"] is False
        assert "可用 celltype: DFF_X1, BUF_X2" in result["errors"][0]
        assert result["available_celltypes"] == ["DFF_X1", "BUF_X2"]

    def test_cell_detail_unknown_instance(self, tmp_path: Path) -> None:
        path = _write(tmp_path, SDF_MAIN)
        result = sdf_service.sdf_cell_detail(path, "DFF_X1", "u_nope")
        assert result["ok"] is False
        assert result["available_instances"] == ["u_core/u_ff1"]
        assert result["n_available_instances"] == 1
        top = sdf_service.sdf_cell_detail(path, "DFF_X1")
        assert top["ok"] is False
        assert "'<top>'" in top["errors"][0]

    def test_error_envelopes_errors_list_of_str(self, tmp_path: Path) -> None:
        failures = [
            sdf_service.parse_sdf_file(tmp_path / "x.sdf"),
            sdf_service.sdf_report(tmp_path / "x.sdf"),
            sdf_service.sdf_cell_detail(tmp_path / "x.sdf", "A"),
        ]
        for env in failures:
            assert env["ok"] is False
            assert isinstance(env["errors"], list)
            assert all(isinstance(e, str) for e in env["errors"])

    def test_service_deterministic(self, tmp_path: Path) -> None:
        path = _write(tmp_path, SDF_MAIN)
        a = sdf_service.sdf_report(path)
        b = sdf_service.sdf_report(path)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

# ══════════════════════════ CLI 两叶 ══════════════════════════

class TestCli:
    def test_parse_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(sdf_app, ["parse", "--file", _write(tmp_path, SDF_MAIN),
                                      "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["celltypes"] == ["DFF_X1", "BUF_X2"]
        assert envelope["cells"][0]["delays"]["IOPATH"][0]["rise_triple"]["min_s"] == 1e-10

    def test_parse_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(sdf_app, ["parse", "--file", str(tmp_path / "no.sdf"),
                                      "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_report_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(sdf_app, ["report", "--file", _write(tmp_path, SDF_MAIN),
                                      "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["timing_check_summary"]["types_present"] == [
            "SETUP", "HOLD", "WIDTH"]

    def test_report_json_failure_envelope(self, tmp_path: Path) -> None:
        bad = _write(tmp_path, SDF_MAIN.replace("(TIMESCALE 1ns)", "(TIMESCALE 7ns)"))
        res = runner.invoke(sdf_app, ["report", "--file", bad, "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert "fail-closed" in envelope["errors"][0]

    def test_parse_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(sdf_app, ["parse", "--file", _write(tmp_path, SDF_MAIN)])
        assert res.exit_code == 0, res.output
        for needle in ("DFF_X1", "BUF_X2", "u_core/u_ff1", "IOPATH=2", "CELLDIVIDER"):
            assert needle in res.output

    def test_report_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(sdf_app, ["report", "--file", _write(tmp_path, SDF_MAIN)])
        assert res.exit_code == 0, res.output
        assert "TIMINGCHECK 汇总: total=3" in res.output
        assert "SETUP" in res.output and "WIDTH" in res.output

    def test_human_output_escapes_markup_like_names(self, tmp_path: Path) -> None:
        text = (f"(DELAYFILE {_MINI_HEADER} "
                '(CELL (CELLTYPE "X") (INSTANCE blk[a])))')
        res = runner.invoke(sdf_app, ["parse", "--file", _write(tmp_path, text)])
        assert res.exit_code == 0, res.output
        assert "blk[a]" in res.output

    def test_human_failure_exit_1(self, tmp_path: Path) -> None:
        res = runner.invoke(sdf_app, ["parse", "--file", str(tmp_path / "no.sdf")])
        assert res.exit_code == 1
        assert "SDF 解析失败" in res.output

    def test_help_builds_no_bare_percent(self) -> None:
        # #305 家法：--help 真构建 + 零裸 %
        for leaf in (["parse", "--help"], ["report", "--help"], ["--help"]):
            res = runner.invoke(sdf_app, leaf)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_missing_file_flag_fails(self) -> None:
        res = runner.invoke(sdf_app, ["parse"])
        assert res.exit_code != 0

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：sdf 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(sdf_service.__file__).parent.parent.joinpath(
            "cli", "domains", "sdf.py").read_text(encoding="utf-8")
        assert source.count('@sdf_app.command("parse")') == 1
        assert source.count('@sdf_app.command("report")') == 1
        assert source.count("@sdf_app.command(") == 2
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
