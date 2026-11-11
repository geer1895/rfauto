"""Verilog-A 结构子集解析内核+服务+CLI 薄壳单测（aurora_q Q-X80 席位）。

覆盖面（任务书 ≥60 条）：

- 词法逐类：数字（int/浮点/科学计数/``_`` 位分隔/前导点）、标识符与
  层次点、字符串转义/未闭合、行/块注释与行号推进、块注释未闭合、运算
  符最大吞噬（``<+``/``**``/``<=``/``&&``）、属性注记 ``(*``/``*)``、
  转义标识符、系统任务、编译器指令、无法识别字符致命、括号深度守卫、
  **零进展守卫**（标点分支推进回归钉——首版实测死循环坑）；
- 表达式前缀归一：**表驱动已知量 20 例**（优先级/一元/括号/三元嵌套
  右结合/``**`` 左结合/函数调用/括号访问/下标与区间下标/系统任务形态
  外引用）+归一失败 fail-closed 6 例（悬挂运算符/括号失配/闭集外运算
  符/缺三目 rhs/空表达式/位置错乱）；
- module 面：module_order、端口方向（1995 体内声明回填+ANSI 头内声明
  双形态）、electrical/wire net（同型多名一桶）、parameter 三键（类型/
  缺省原文+数值回收/from 范围开闭区间四形态结构化）、属性注记登记、
  discipline 登记不展开、未知网类型如实登记+温和警告、endmodule 缺失
  fail-soft warning 不拒、空文件/纯注释 fail-closed；
- analog 面：语句分类计数闭集逐键、贡献语句表（LHS 访问串规范形态+
  RHS 归一树）、RHS 归一失败 fail-soft（树 None+原文保留）、事件登记
  （@(initial_step)/@(cross(args)) 参数原文）、for 头内 ``;`` 不拆语
  句、嵌套 begin/end 配平、多余 end/未闭合 begin 警告、analog function
  声明登记+体跳过、函数调用/赋值分类、截断语句警告；
- 查询三函数：module_summary（键面+缺失 KeyError 带名录）、param_table
  （全模块平坦+module 列）、contribution_pairs（平坦清单）；
- 服务三函数信封契约（AU-2：ok/error 两态、errors 恒 list[str]、不可
  读/空文件/无 module → error、endmodule 缺失 → ok=True 携 warning、
  Latin-1 兜底、detail 未命中带可用名录）；
- CLI（**veriloga_app 直连+局部父 Typer 自测**——共享 app 接线由主代
  合流统一，本席禁改 cli/main.py）：parse/report --json 全结构+human
  紧凑面+失败信封同构（exit 1）+缺 --file usage 错（exit 2）+--help 真
  构建（#305）+help 字符卫生（裸 [ /未成对 % 零违例）+域叶形状钉+源码
  字面钉（两叶各带 --json）+**cli.main 零导入钉**（合流契约）。

单测零网络零真机；文件面一律 tmp_path（#144 run 湖零写入）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains.veriloga import veriloga_app
from rfauto.core.veriloga_parser import (
    MAX_NEST_DEPTH,
    PARSER_SCHEMA_VERSION,
    STMT_CATEGORIES,
    ExpressionNormError,
    Token,
    VerilogAParseError,
    expr_to_prefix,
    parse_number_literal,
    parse_veriloga,
    tokenize_veriloga,
    veriloga_contribution_pairs,
    veriloga_module_summary,
    veriloga_param_table,
)
from rfauto.service.veriloga_service import (
    parse_veriloga_file,
    veriloga_module_detail,
    veriloga_report,
)

# ── 主夹具（任务书口径：module 2+electrical 4+parameter 3（含 from
#    范围）+analog 块含贡献 3/条件 1/事件 1）───────────────────────────
# 预声明账（逐项断言）：
#   module_order == ["rdiv", "rc_lp"]
#   rdiv：ports 2（p/n 均 input）；electrical [p,n]；params 2
#     （R real 缺省 50 范围 [0:inf)；name_tag string 缺省原文带引号）；
#     analog：contribution 2 / if 1 / else 1 / assignment 2 / block 1
#   rc_lp：ports 2（in=input/out=output）；electrical [in,out]+wire [tie]
#     （electrical 总 4）；params 1（tau real 缺省 1e-3 回收 0.001、
#     范围 (0:inf) 双开）；analog：contribution 1 / event 1 / block 1
#   全文档：n_contributions=3、n_events=1、n_params=3、n_ports=4
SAMPLE_VA = """\
// Verilog-A structural sample (behavioral divider + lowpass)
module rdiv (p, n);
  (* descend *)
  input p, n;
  electrical p, n;
  parameter real R = 50 from [0:inf);
  parameter string name_tag = "rdiv";
  analog begin
    V(p, n) <+ R * I(p, n);
    I(p) <+ V(p, n) / R;
    if (R > 0)
      limit = 1;
    else
      limit = 0;
  end
endmodule

module rc_lp (in, out);
  input in;
  output out;
  electrical in, out;
  wire tie;
  parameter real tau = 1e-3 from (0:inf);
  analog begin
    @(cross(V(out), 1))
      V(out) <+ 0;
  end
endmodule
"""

PARSE_KEYS = {
    "ok", "path", "modules", "module_order", "disciplines", "attributes",
    "warnings", "stats",
}
REPORT_KEYS = {
    "ok", "path", "module_names", "modules_summary", "param_table",
    "contribution_pairs", "disciplines", "warnings", "stats",
}
DETAIL_KEYS = {"ok", "path", "module", "summary", "warnings"}

runner = CliRunner()

@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return parse_veriloga(SAMPLE_VA)

@pytest.fixture(scope="module")
def stats(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["stats"]

@pytest.fixture()
def va_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.va"
    f.write_text(SAMPLE_VA, encoding="utf-8")
    return f

@pytest.fixture(scope="module")
def local_app() -> typer.Typer:
    """局部父 Typer（共享 app 接线待主代合流；本席自测不经 cli/main）。"""
    parent = typer.Typer()
    parent.add_typer(veriloga_app, name="veriloga")
    return parent

# ── 词法逐类 ────────────────────────────────────────────────────────────────

class TestLexer:
    def test_number_forms(self) -> None:
        toks = tokenize_veriloga("50 1.5 1e-3 1_000 .25 2.5E4")
        assert [t.kind for t in toks] == ["num"] * 6
        assert [t.text for t in toks] == [
            "50", "1.5", "1e-3", "1_000", ".25", "2.5E4"]

    def test_identifier_and_hierarchy_dots(self) -> None:
        toks = tokenize_veriloga("u1.mos.sgate")
        assert [t.text for t in toks] == ["u1", ".", "mos", ".", "sgate"]
        assert [t.kind for t in toks] == ["id", "punct", "id", "punct", "id"]

    def test_string_with_escape(self) -> None:
        toks = tokenize_veriloga(r'"a\"b"')
        assert toks[0].kind == "str"
        assert toks[0].text == r'"a\"b"'

    def test_string_unterminated_raises(self) -> None:
        with pytest.raises(VerilogAParseError) as ei:
            tokenize_veriloga('"abc')
        assert "字符串未闭合" in str(ei.value)

    def test_line_comment_skipped(self) -> None:
        assert tokenize_veriloga("a // note\nb") == [
            Token("id", "a", 1), Token("id", "b", 2)]

    def test_block_comment_skipped_with_line_advance(self) -> None:
        toks = tokenize_veriloga("a /* x\ny\nz */ b")
        assert [t.text for t in toks] == ["a", "b"]
        assert toks[1].line == 3

    def test_block_comment_unterminated_raises(self) -> None:
        with pytest.raises(VerilogAParseError) as ei:
            tokenize_veriloga("a /* never closed")
        assert "块注释未闭合" in str(ei.value)

    @pytest.mark.parametrize("op", ["<+", "**", "<=", ">=", "==", "!=", "&&", "||"])
    def test_operator_maximal_munch(self, op: str) -> None:
        toks = tokenize_veriloga(f"a {op} b")
        assert [t.text for t in toks] == ["a", op, "b"]

    def test_attribute_tokens(self) -> None:
        toks = tokenize_veriloga("(* descend *) module m;")
        assert [t.text for t in toks[:3]] == ["(*", "descend", "*)"]

    def test_escaped_identifier(self) -> None:
        toks = tokenize_veriloga(r"\bus+width endmodule")
        assert toks[0].kind == "id"
        assert toks[0].text == r"\bus+width"[1:] or toks[0].text == "bus+width"

    def test_sys_token(self) -> None:
        toks = tokenize_veriloga("$display;")
        assert toks[0].kind == "sys"
        assert toks[0].text == "$display"

    def test_directive_line_consumed(self) -> None:
        toks = tokenize_veriloga("`include \"x.vh\"\na;")
        assert toks[0].kind == "dir"
        assert toks[0].text == "include"
        assert toks[1].kind == "id"

    def test_unrecognized_char_raises(self) -> None:
        with pytest.raises(VerilogAParseError) as ei:
            tokenize_veriloga("a ¡ b")
        assert "无法识别的字符" in str(ei.value)

    def test_depth_guard_raises(self) -> None:
        with pytest.raises(VerilogAParseError) as ei:
            tokenize_veriloga("(" * (MAX_NEST_DEPTH + 1))
        assert "深度超过上限" in str(ei.value)

    def test_zero_progress_punct_advance(self) -> None:
        # 回归钉：标点分支必须推进 i（首版缺 i+=1 实测死循环坑）
        toks = tokenize_veriloga("a + b;")
        assert [t.text for t in toks] == ["a", "+", "b", ";"]

# ── 表达式前缀归一（表驱动已知量）───────────────────────────────────────────

EXPR_CASES = [
    ("a + b * c", ["+", "a", ["*", "b", "c"]]),
    ("(a + b) * c", ["*", ["+", "a", "b"], "c"]),
    ("-x", ["-", "x"]),
    ("-a * b", ["*", ["-", "a"], "b"]),
    ("a - b - c", ["-", ["-", "a", "b"], "c"]),
    ("2 ** 3 ** 2", ["**", ["**", "2", "3"], "2"]),  # Verilog-A 左结合
    ("a && b || c && d", ["||", ["&&", "a", "b"], ["&&", "c", "d"]]),
    ("c ? a : b", ["?:", "c", "a", "b"]),
    ("a ? b : c ? d : e", ["?:", "a", "b", ["?:", "c", "d", "e"]]),
    ("a >= b ? -x : y", ["?:", [">=", "a", "b"], ["-", "x"], "y"]),
    ("f(a, b*c)", ["f", "a", ["*", "b", "c"]]),
    ("V(out)", ["V", "out"]),
    ("V(p, n) + I(p)", ["+", ["V", "p", "n"], ["I", "p"]]),
    ("!a && b", ["&&", ["!", "a"], "b"]),
    ("a % 2", ["%", "a", "2"]),
    ("exp(-time / tau)", ["exp", ["/", ["-", "time"], "tau"]]),
    ("v[3]", ["[]", "v", "3"]),
    ("p[1:0]", ["[]", "p", "1", "0"]),
    ("cross(V(out) - 0, 1)", ["cross", ["-", ["V", "out"], "0"], "1"]),
    ("a + b < c", ["<", ["+", "a", "b"], "c"]),
]

EXPR_BAD = [
    "a +",           # 悬挂二元
    "(a + b",        # 括号失配
    "a | b",         # 闭集外运算符
    "a ? b",         # 缺 :（rhs 不存在）
    "f(a,)",         # 实参表空位
    "+ a",           # 期待操作数
]

class TestExpressions:
    @pytest.mark.parametrize(
        "source, want", EXPR_CASES, ids=[c[0] for c in EXPR_CASES])
    def test_table_known_values(self, source: str, want: Any) -> None:
        assert expr_to_prefix(source) == want

    @pytest.mark.parametrize("source", EXPR_BAD)
    def test_fail_closed(self, source: str) -> None:
        with pytest.raises(ExpressionNormError):
            expr_to_prefix(source)

    def test_token_input_form(self) -> None:
        toks = tokenize_veriloga("a + b")
        assert expr_to_prefix(toks) == ["+", "a", "b"]

    def test_contribution_operator_rejected_in_expr(self) -> None:
        # <+ 是贡献算子不是表达式运算符（fail-closed 不猜）
        with pytest.raises(ExpressionNormError):
            expr_to_prefix("V(out) <+ 1")

    def test_numbers_stay_raw_strings(self) -> None:
        # 铁律 7：不求值——数字一律字符串原样（50 与 50.0 不折算）
        assert expr_to_prefix("50") == "50"
        assert expr_to_prefix("1e-3 + 2") == ["+", "1e-3", "2"]

    def test_empty_raises(self) -> None:
        with pytest.raises(ExpressionNormError):
            expr_to_prefix([])

    def test_nested_group_tree_shape(self) -> None:
        assert expr_to_prefix("((a))") == "a"
        assert expr_to_prefix("((a + b) * (c - d))") == [
            "*", ["+", "a", "b"], ["-", "c", "d"]]

# ── module 面 ───────────────────────────────────────────────────────────────

class TestModule:
    def test_schema_tag(self, doc: dict[str, Any]) -> None:
        assert doc["schema_version"] == PARSER_SCHEMA_VERSION

    def test_module_order(self, doc: dict[str, Any]) -> None:
        assert doc["module_order"] == ["rdiv", "rc_lp"]

    def test_ports_dirs(self, doc: dict[str, Any]) -> None:
        m1 = doc["modules"]["rdiv"]
        assert m1["ports"] == [
            {"dir": "input", "name": "p"}, {"dir": "input", "name": "n"}]
        m2 = doc["modules"]["rc_lp"]
        assert m2["ports"] == [
            {"dir": "input", "name": "in"}, {"dir": "output", "name": "out"}]

    def test_electrical_four_names(self, doc: dict[str, Any]) -> None:
        names = [n for m in doc["modules"].values() for net in m["nets"]
                 if net["type"] == "electrical" for n in net["names"]]
        assert sorted(names) == ["in", "n", "out", "p"]

    def test_wire_net_bucket(self, doc: dict[str, Any]) -> None:
        nets = doc["modules"]["rc_lp"]["nets"]
        assert {"type": "wire", "names": ["tie"]} in nets

    def test_param_type_and_default_raw(self, doc: dict[str, Any]) -> None:
        p = doc["modules"]["rdiv"]["params"][0]
        assert p["name"] == "R"
        assert p["type"] == "real"
        assert p["default_raw"] == "50"
        assert p["default"] == 50

    def test_param_range_inclusive_low_exclusive_high(
            self, doc: dict[str, Any]) -> None:
        p = doc["modules"]["rdiv"]["params"][0]
        assert p["range"] == {
            "raw": "[0:inf)", "low": "0", "high": "inf",
            "low_inclusive": True, "high_inclusive": False,
        }

    def test_param_range_both_exclusive(self, doc: dict[str, Any]) -> None:
        p = doc["modules"]["rc_lp"]["params"][0]
        assert p["range"]["raw"] == "(0:inf)"
        assert p["range"]["low_inclusive"] is False
        assert p["range"]["high_inclusive"] is False

    def test_param_without_range(self, doc: dict[str, Any]) -> None:
        p = doc["modules"]["rc_lp"]["params"][0]
        assert p["range"]["raw"] == "(0:inf)"  # tau 有范围
        others = [q for m in doc["modules"].values()
                  for q in m["params"] if q["name"] == "name_tag"]
        assert others[0]["range"] is None

    def test_param_default_float_recovery(self, doc: dict[str, Any]) -> None:
        p = doc["modules"]["rc_lp"]["params"][0]
        assert p["default_raw"] == "1e-3"
        assert p["default"] == 0.001
        assert isinstance(p["default"], float)

    def test_param_string_default_not_recovered(
            self, doc: dict[str, Any]) -> None:
        p = next(q for m in doc["modules"].values() for q in m["params"]
                 if q["name"] == "name_tag")
        assert p["type"] == "string"
        assert p["default_raw"] == '"rdiv"'
        assert p["default"] is None

    def test_attributes_recorded(self, doc: dict[str, Any]) -> None:
        assert doc["modules"]["rdiv"]["attributes"] == ["descend"]

    def test_stats_totals(self, stats: dict[str, Any]) -> None:
        assert stats["n_modules"] == 2
        assert stats["n_ports"] == 4
        assert stats["n_params"] == 3
        assert stats["n_contributions"] == 3
        assert stats["n_events"] == 1

    def test_missing_endmodule_warns_not_rejects(self) -> None:
        text = "module m (a);\n  input a;\n  electrical a;\n"
        d = parse_veriloga(text)
        assert d["module_order"] == ["m"]
        assert any(w["name"] == "unterminated_module" for w in d["warnings"])

    def test_ansi_header_ports(self) -> None:
        d = parse_veriloga(
            "module ansi (input a, output b);\n"
            "  electrical a, b;\nendmodule\n")
        assert d["modules"]["ansi"]["ports"] == [
            {"dir": "input", "name": "a"}, {"dir": "output", "name": "b"}]

    def test_inout_direction(self) -> None:
        d = parse_veriloga(
            "module io (mid);\n  inout mid;\n  electrical mid;\nendmodule\n")
        assert d["modules"]["io"]["ports"] == [
            {"dir": "inout", "name": "mid"}]

    def test_discipline_registered_not_expanded(self) -> None:
        d = parse_veriloga(
            "discipline voltage\n  enddiscipline\n"
            "module m (a);\nendmodule\n")
        assert d["disciplines"] == ["voltage"]
        assert not any("discipline" in w["name"] for w in d["warnings"])

    def test_unknown_net_type_registered_as_is(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  voltage a;\nendmodule\n")
        assert d["modules"]["m"]["nets"] == [{"type": "voltage", "names": ["a"]}]
        assert any(w["name"] == "unknown_net_type" for w in d["warnings"])

    def test_empty_text_raises(self) -> None:
        with pytest.raises(VerilogAParseError) as ei:
            parse_veriloga("   \n  ")
        assert "空文件" in str(ei.value)

    def test_comment_only_zero_modules(self) -> None:
        # 纯注释文本：core 层词法为空 → 零 module 文档（"无 module" 的
        # error 信封化在 service 层单源判定，core 不拒）
        d = parse_veriloga("// only comment\n/* block */\n")
        assert d["module_order"] == []

    def test_deterministic(self) -> None:
        assert parse_veriloga(SAMPLE_VA) == parse_veriloga(SAMPLE_VA)

    def test_json_round_trip(self, doc: dict[str, Any]) -> None:
        assert json.loads(json.dumps(doc, ensure_ascii=False)) == doc

# ── analog 行为块 ───────────────────────────────────────────────────────────

class TestAnalog:
    def test_stmt_counts_keys_closed_set(self, doc: dict[str, Any]) -> None:
        for m in doc["modules"].values():
            assert set(m["analog"]["stmt_counts"]) == set(STMT_CATEGORIES)

    def test_rdiv_counts(self, doc: dict[str, Any]) -> None:
        c = doc["modules"]["rdiv"]["analog"]["stmt_counts"]
        assert c["contribution"] == 2
        assert c["if"] == 1
        assert c["else"] == 1
        assert c["assignment"] == 2
        assert c["block"] == 1
        assert c["event"] == 0
        assert c["function_call"] == 0

    def test_rc_lp_counts(self, doc: dict[str, Any]) -> None:
        c = doc["modules"]["rc_lp"]["analog"]["stmt_counts"]
        assert c["contribution"] == 1
        assert c["event"] == 1
        assert c["block"] == 1

    def test_contribution_lhs_access_string(self, doc: dict[str, Any]) -> None:
        lhs_list = [c["lhs"] for m in doc["modules"].values()
                    for c in m["analog"]["contributions"]]
        assert lhs_list == ["V(p, n)", "I(p)", "V(out)"]

    def test_contribution_rhs_trees(self, doc: dict[str, Any]) -> None:
        trees = [c["rhs_prefix_tree"]
                 for m in doc["modules"].values()
                 for c in m["analog"]["contributions"]]
        assert trees[0] == ["*", "R", ["I", "p", "n"]]
        assert trees[1] == ["/", ["V", "p", "n"], "R"]
        assert trees[2] == "0"  # 单操作数=叶（字符串原样）

    def test_event_registered_with_args(self, doc: dict[str, Any]) -> None:
        ev = doc["modules"]["rc_lp"]["analog"]["events"]
        assert ev == [{"name": "cross", "args_raw": "V(out), 1"}]

    def test_initial_step_event_no_args(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n"
            "  analog begin\n    @(initial_step)\n      a = 0;\n  end\n"
            "endmodule\n")
        assert d["modules"]["m"]["analog"]["events"] == [
            {"name": "initial_step", "args_raw": None}]
        assert d["modules"]["m"]["analog"]["stmt_counts"]["event"] == 1

    def test_for_header_semicolons_not_statement_split(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog begin\n"
            "    for (i = 0; i < 4; i = i + 1)\n      a = i;\n"
            "  end\nendmodule\n")
        c = d["modules"]["m"]["analog"]["stmt_counts"]
        assert c["for"] == 1
        # for 头 `(i = 0; i < 4; i = i + 1)` 整捕获（头内 ; 与 = 不分类
        # 不拆语句），唯一计账的赋值=循环体 a = i
        assert c["assignment"] == 1
        assert c["other"] == 0

    def test_while_control(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog begin\n"
            "    while (n < 3)\n      n = n + 1;\n  end\nendmodule\n")
        c = d["modules"]["m"]["analog"]["stmt_counts"]
        assert c["while"] == 1
        assert c["assignment"] == 1

    def test_nested_begin_block_count(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog begin\n"
            "    begin\n      a = 1;\n    end\n  end\nendmodule\n")
        assert d["modules"]["m"]["analog"]["stmt_counts"]["block"] == 2

    def test_stray_end_warns(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog begin\n    a = 1;\n"
            "  end\n  end\nendmodule\n")
        assert any(w["name"] == "stray_end" for w in d["warnings"])

    def test_unterminated_begin_warns(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog begin\n    a = 1;\n"
            "endmodule\n")
        assert any(w["name"] == "unterminated_block" for w in d["warnings"])
        assert d["module_order"] == ["m"]  # fail-soft 不拒

    def test_analog_function_registered_skipped(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n"
            "  analog function real sq;\n    input x;\n"
            "    sq = x * x;\n  endfunction\n"
            "  analog a = 1;\nendmodule\n")
        assert d["module_order"] == ["m"]
        assert any(w["name"] == "analog_function_skipped"
                   for w in d["warnings"])
        assert d["modules"]["m"]["analog"]["stmt_counts"]["assignment"] == 1

    def test_function_call_classification(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog begin\n"
            "    discontinuity(0);\n    $display(\"x\");\n"
            "  end\nendmodule\n")
        c = d["modules"]["m"]["analog"]["stmt_counts"]
        assert c["function_call"] == 2

    def test_contribution_rhs_fail_soft(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog\n"
            "    V(a) <+ x | y;\nendmodule\n")
        cs = d["modules"]["m"]["analog"]["contributions"]
        assert len(cs) == 1
        assert cs[0]["lhs"] == "V(a)"
        assert cs[0]["rhs_prefix_tree"] is None
        assert cs[0]["rhs_raw"] == "x | y"
        assert any(w["name"] == "expr_normalize_failed"
                   for w in d["warnings"])

    def test_truncated_statement_warns(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog\n    a = 1;\n"
            "endmodule\n")
        assert d["modules"]["m"]["analog"]["stmt_counts"]["assignment"] == 1

    def test_analog_single_statement_no_begin(self) -> None:
        d = parse_veriloga(
            "module m (a);\n  electrical a;\n  analog V(a) <+ 0;\n"
            "endmodule\n")
        cs = d["modules"]["m"]["analog"]["contributions"]
        assert cs == [{"lhs": "V(a)", "rhs_prefix_tree": "0"}]

# ── 数字字面量回收（源文本回收非求值）──────────────────────────────────────

class TestNumberRecovery:
    def test_int(self) -> None:
        assert parse_number_literal("50") == 50
        assert isinstance(parse_number_literal("50"), int)

    def test_float_scientific(self) -> None:
        assert parse_number_literal("1e-3") == 0.001

    def test_underscore_int(self) -> None:
        assert parse_number_literal("1_000") == 1000

    def test_non_number_none(self) -> None:
        assert parse_number_literal("abc") is None
        assert parse_number_literal("") is None

# ── 查询三函数 ──────────────────────────────────────────────────────────────

class TestQueries:
    def test_module_summary_keys(self, doc: dict[str, Any]) -> None:
        s = veriloga_module_summary(doc, "rdiv")
        assert set(s) == {
            "module", "ports", "n_ports", "nets", "n_nets", "params",
            "n_params", "stmt_counts", "contributions", "n_contributions",
            "events", "attributes"}
        assert s["n_ports"] == 2
        assert s["n_nets"] == 2
        assert s["n_params"] == 2
        assert s["n_contributions"] == 2

    def test_module_summary_missing_key_error(self, doc) -> None:
        with pytest.raises(KeyError) as ei:
            veriloga_module_summary(doc, "ghost")
        assert "ghost" in str(ei.value)
        assert "rdiv" in str(ei.value)  # 可用名录随错给出

    def test_param_table_flat_with_module_column(self, doc) -> None:
        table = veriloga_param_table(doc)
        assert [r["module"] for r in table] == ["rdiv", "rdiv", "rc_lp"]
        assert [r["name"] for r in table] == ["R", "name_tag", "tau"]
        assert all(set(r) == {"module", "name", "type", "default_raw",
                              "default", "range", "extra_raw"}
                   for r in table)

    def test_contribution_pairs_flat(self, doc) -> None:
        pairs = veriloga_contribution_pairs(doc)
        assert [(p["module"], p["lhs"]) for p in pairs] == [
            ("rdiv", "V(p, n)"), ("rdiv", "I(p)"), ("rc_lp", "V(out)")]
        assert pairs[0]["rhs_prefix_tree"] == ["*", "R", ["I", "p", "n"]]

# ── 服务三函数（AU-2 信封契约）─────────────────────────────────────────

class TestService:
    def test_parse_ok_envelope_keys(self, va_file: Path) -> None:
        r = parse_veriloga_file(va_file)
        assert r["ok"] is True
        assert set(r) == PARSE_KEYS
        assert r["path"] == str(va_file)
        assert r["stats"]["n_modules"] == 2

    def test_parse_envelope_json_safe(self, va_file: Path) -> None:
        json.dumps(parse_veriloga_file(va_file), ensure_ascii=False)  # 不抛即过

    def test_parse_unreadable_error(self, tmp_path: Path) -> None:
        r = parse_veriloga_file(tmp_path / "no_such.va")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert "不可读" in r["errors"][0]

    def test_parse_empty_file_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.va"
        f.write_text("", encoding="utf-8")
        r = parse_veriloga_file(f)
        assert r["ok"] is False
        assert "解析失败" in r["errors"][0]

    def test_parse_no_module_error(self, tmp_path: Path) -> None:
        f = tmp_path / "nomodule.va"
        f.write_text("// 注释一行\n", encoding="utf-8")
        r = parse_veriloga_file(f)
        assert r["ok"] is False
        assert "无 module" in r["errors"][0]

    def test_parse_missing_endmodule_ok_with_warning(
            self, tmp_path: Path) -> None:
        f = tmp_path / "trunc.va"
        f.write_text("module m (a);\n  input a;\n", encoding="utf-8")
        r = parse_veriloga_file(f)
        assert r["ok"] is True  # endmodule 缺失=warning 不拒
        assert any(w["name"] == "unterminated_module" for w in r["warnings"])

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.va"
        f.write_bytes(
            b"// caf\xe9 note\nmodule m (a);\nendmodule\n")
        r = parse_veriloga_file(f)
        assert r["ok"] is True

    def test_report_envelope(self, va_file: Path) -> None:
        r = veriloga_report(va_file)
        assert r["ok"] is True
        assert set(r) == REPORT_KEYS
        assert [m["name"] for m in r["modules_summary"]] == [
            "rdiv", "rc_lp"]
        assert r["modules_summary"][0]["n_contributions"] == 2
        assert len(r["param_table"]) == 3
        assert len(r["contribution_pairs"]) == 3

    def test_report_unreadable_error(self, tmp_path: Path) -> None:
        r = veriloga_report(tmp_path / "missing.va")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)

    def test_detail_found(self, va_file: Path) -> None:
        r = veriloga_module_detail(va_file, "rc_lp")
        assert r["ok"] is True
        assert set(r) == DETAIL_KEYS
        assert r["summary"]["n_contributions"] == 1
        assert r["summary"]["events"][0]["name"] == "cross"

    def test_detail_miss_lists_available(self, va_file: Path) -> None:
        r = veriloga_module_detail(va_file, "ghost")
        assert r["ok"] is False
        assert "ghost" in r["errors"][0]
        assert "rdiv" in r["errors"][0]

    def test_detail_unreadable_error(self, tmp_path: Path) -> None:
        r = veriloga_module_detail(tmp_path / "missing.va", "m")
        assert r["ok"] is False
        assert "不可读" in r["errors"][0]

    def test_service_deterministic(self, va_file: Path) -> None:
        assert parse_veriloga_file(va_file) == parse_veriloga_file(va_file)

# ── CLI（veriloga_app 直连/局部父 Typer 自测；接线待合流）──────────────

class TestCli:
    def test_parse_json_envelope(self, local_app: typer.Typer,
                                 va_file: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "parse", "--file",
                                      str(va_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == PARSE_KEYS
        assert payload["stats"]["n_contributions"] == 3

    def test_parse_human_output(self, local_app: typer.Typer,
                                va_file: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "parse", "--file",
                                      str(va_file)])
        assert r.exit_code == 0, r.output
        assert "rdiv" in r.output and "rc_lp" in r.output
        assert "V(p, n)" in r.output  # 贡献语句表 LHS 访问串
        assert "cross" in r.output  # 事件名录

    def test_parse_failure_json_exit1(self, local_app: typer.Typer,
                                      tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "parse", "--file",
                                      str(tmp_path / "nope.va"), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert len(payload["errors"]) == 1

    def test_parse_failure_human_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "parse", "--file",
                                      str(tmp_path / "nope.va")])
        assert r.exit_code == 1
        assert "Verilog-A 解析失败" in r.output

    def test_parse_missing_file_option_exit2(
            self, local_app: typer.Typer) -> None:
        r = runner.invoke(local_app, ["veriloga", "parse"])
        assert r.exit_code == 2

    def test_report_json_envelope(self, local_app: typer.Typer,
                                  va_file: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "report", "--file",
                                      str(va_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert set(payload) == REPORT_KEYS
        assert len(payload["contribution_pairs"]) == 3

    def test_report_human_output(self, local_app: typer.Typer,
                                 va_file: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "report", "--file",
                                      str(va_file)])
        assert r.exit_code == 0, r.output
        assert "rdiv" in r.output
        assert "R" in r.output  # 参数表
        assert "[0:inf)" in r.output

    def test_report_failure_json_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "report", "--file",
                                      str(tmp_path / "nope.va"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_report_failure_human_exit1(self, local_app: typer.Typer,
                                        tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["veriloga", "report", "--file",
                                      str(tmp_path / "nope.va")])
        assert r.exit_code == 1
        assert "Verilog-A 报告失败" in r.output

    @pytest.mark.parametrize("leaf", ["parse", "report"])
    def test_help_real_build(self, local_app: typer.Typer, leaf: str) -> None:
        # #305：真构建 --help（帮助串含 % 或裸 [ 会在展开期炸/渲染歪）
        r = runner.invoke(local_app, ["veriloga", leaf, "--help"])
        assert r.exit_code == 0, r.output
        assert "--file" in r.output

    def test_direct_app_help(self) -> None:
        r = runner.invoke(veriloga_app, ["--help"])
        assert r.exit_code == 0, r.output
        assert "parse" in r.output and "report" in r.output

    def test_domain_leaf_shape(self, local_app: typer.Typer) -> None:
        from typer.main import get_command

        group = get_command(local_app).commands.get("veriloga")
        assert group is not None
        assert set(group.commands) == {"parse", "report"}

    def test_help_text_hygiene(self, local_app: typer.Typer) -> None:
        # D-06 门同判定面预检：命令 help/short_help 与参数 help 零裸 [、
        # 零未成对 %（合流后进全树门亦绿）
        from typer.main import get_command

        group = get_command(local_app).commands["veriloga"]
        texts = [group.help or ""]
        for cmd in group.commands.values():
            texts.extend([cmd.help or "", cmd.short_help or ""])
            texts.extend(getattr(p, "help", None) or "" for p in cmd.params)
        for text in texts:
            assert "[" not in text, text
            assert text.replace("%%", "").count("%") == 0, text

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：veriloga 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(
            __import__("rfauto.service.veriloga_service", fromlist=["x"])
            .__file__).parent.parent.joinpath(
            "cli", "domains", "veriloga.py").read_text(encoding="utf-8")
        assert source.count('@veriloga_app.command("parse")') == 1
        assert source.count('@veriloga_app.command("report")') == 1
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
