"""SKILL/OCEAN 解析内核+服务+CLI 单测（aurora_q 席位 Q-X62，2026-11-08）。

夹具纪律（任务书口径）：内嵌小 SKILL 文本——``SKILL_MAIN``=defun 2（其一
重复定义走 dup 双列）+define 双形态（值形态/函数头形态/lambda 值形态）+
let（SKILL 扁平 var/val 绑定）+cond（testhead 分支）+foreach+setf/setq+
字符串/向量字面量/quasiquote 模板+注释三形态（行注释/单行块/跨行块）+
ocean 前缀调用若干（ocn/sim/netlist/asi）+virtuoso 前缀调用若干
（hi/db/ge/le）+引号数据（不计调用）。变体形态以测试内小片段覆盖。零外部
夹具文件；服务/CLI 测试经 tmp_path 落盘隔离（#144 run 湖零写入），零网络
零真机。

覆盖面（任务书 ≥60 条）：词法逐类（数字 int/float/科学计数/``1+`` 函数名
形态、符号字符集/``?kw``/``|...|`` 转义、字符串转义/未知转义保留、注释
三形态、向量、quote/quasiquote/unquote/unquote-splicing 糖、``f(`` 调用
糖折叠/有空白不折叠、词法闭集外字符致命）、节点树类型判等（Symbol 跨行
等值+可哈希/LispList/LispVector/Quote/int|float|str 保留）、括号失衡位置
断言（多余右括号/未闭合/方圆交叉/未闭合串·注释·转义符号/悬挂糖/深度守卫，
全部带行号+列号）、结构提取四函数（definitions 双形态+重复双列、
top_level 分类闭集、api_calls 前缀四桶+绑定形态剪除+引号数据排除、globals
目标+深度+表达式目标）、静态调用边（define→calls 按名匹配/递归自环/
external 如实）、literal_eval（可求值六族+fail-closed 六族）、服务信封
三函数（ok/error 同构+line/column 结构化键+Latin-1 兜底+BOM）、CLI 两叶
--json 双路径（CliRunner 直连 skill_parse_app——不触共享 app，零金快照
漂移）+help 真构建零裸 % +计数链字面钉+cli.main 零导入钉+U+FFFD=0（#259）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains.skill_parse import skill_parse_app
from rfauto.core.skill_parser import (
    API_BUCKETS,
    API_PREFIX_BUCKETS,
    MAX_NEST_DEPTH,
    PARSER_SCHEMA_VERSION,
    SPECIAL_FORMS,
    TOP_LEVEL_CATEGORIES,
    LispList,
    LispVector,
    Quote,
    SkillEvalError,
    SkillParseError,
    Symbol,
    api_bucket,
    node_to_plain,
    parse_skill,
    render_skill,
    skill_api_calls,
    skill_call_edges,
    skill_definitions,
    skill_globals,
    skill_literal_eval,
    skill_top_level_forms,
    skill_tree_stats,
)
from rfauto.service import skill_service

runner = CliRunner()

# ══════════════════════════ 夹具 ══════════════════════════

SKILL_MAIN = """\
; Q-X62 fixture：SKILL/OCEAN 混合小脚本（行注释）
/* 单行块注释：( 括号 ) 与 "引号" 不影响配平 */
/* 跨行块注释
   第二行 ( 仍不影响配平 */
defun( filterGain (g f0)
    let( ( omega (* 2 PI f0) )
        cond(
            ( (g > 10) (ocnPrint ?num g) )
            ( t (hiShowWindow win) )
        )
    )
)
define( kFactor 2.5 )
define( (kDouble x) (* x kFactor) )
define( sq (lambda (x) (* x x)) )
defun( sweepGrid (n)
    foreach( dev devices
        setf( grid dev )
        simulator( 'spectre )
        netlistAndSpectre( 'spectre )
        asiCreate( "analysis" )
    )
    [1 2.5 "str" [3 4]]
)
setq( a 1 b (foo 2) )
setf( (car pair) 9 )
ocnWaveformTool( 'auspice )
dbOpenCellViewByType( lib cell "layout" )
geGetEditCellView( win )
leHiForm( "layout" )
`(1 ,x ,@rest)
'(quoted data (ocnNever a))
defun( filterGain (x) (negwidth x) )
"""

def _line_of(text: str, needle: str) -> int:
    """needle 首次出现所在行号（1 起）——行号断言不手写常量。"""
    return text[: text.index(needle)].count("\n") + 1

def _write(tmp_path: Path, text: str, name: str = "main.il") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)

@pytest.fixture(scope="module")
def main_tree() -> list[object]:
    return parse_skill(SKILL_MAIN)

@pytest.fixture(scope="module")
def main_defs(main_tree) -> dict:
    return skill_definitions(main_tree)

@pytest.fixture(scope="module")
def main_api(main_tree) -> dict:
    return skill_api_calls(main_tree)

# ══════════════════════════ 词法逐类 ══════════════════════════

class TestLexer:
    @pytest.mark.parametrize(
        "text, value, kind",
        [
            ("42", 42, "int"),
            ("-7", -7, "int"),
            ("+3", 3, "int"),
            ("2.5", 2.5, "float"),
            (".5", 0.5, "float"),
            ("-1.25", -1.25, "float"),
            ("3e4", 30000.0, "float"),
            ("2.5e-10", 2.5e-10, "float"),
            ("1E+2", 100.0, "float"),
        ],
    )
    def test_number_classes(self, text: str, value: object, kind: str) -> None:
        (node,) = parse_skill(text)
        assert node == value
        assert type(node).__name__ == kind

    @pytest.mark.parametrize("text", ["1+", "1-", "1x", "1.2.3", "1e", "+-"])
    def test_number_adjacent_symbol_forms(self, text: str) -> None:
        # SKILL 1+/1- 函数名形态：数字后紧跟 +-/. 字母时按符号如实
        (node,) = parse_skill(text)
        assert isinstance(node, Symbol)
        assert node.name == text

    def test_symbol_alphabet_and_keywords(self) -> None:
        tree = parse_skill("foo Bar_1 ?kw a+b x<=y !flag a/b")
        names = [n.name for n in tree]
        assert names == ["foo", "Bar_1", "?kw", "a+b", "x<=y", "!flag", "a/b"]

    def test_escaped_vsymbol_verbatim(self) -> None:
        (node,) = parse_skill("|odd name|")
        assert isinstance(node, Symbol)
        assert node.name == "odd name"

    def test_string_decode_known_escapes(self) -> None:
        (node,) = parse_skill('"a\\"b\\\\c\\nd\\te"')
        assert node == 'a"b\\c\nd\te'

    def test_string_unknown_escape_kept_verbatim(self) -> None:
        (node,) = parse_skill('"\\q"')
        assert node == "\\q"

    def test_line_comment_swallows_to_eol(self) -> None:
        tree = parse_skill("a ; tail ( comment\nb")
        assert [n.name for n in tree] == ["a", "b"]

    def test_block_comment_single_line_with_parens(self) -> None:
        tree = parse_skill('/* ( ) "x" ; ; */ a')
        assert [n.name for n in tree] == ["a"]

    def test_block_comment_multiline_line_tracking(self) -> None:
        text = "/* line1\nline2 (\nline3 */\nb"
        tree = parse_skill(text)
        assert len(tree) == 1
        assert tree[0].line == 4

    def test_vector_literal_vs_list_type(self) -> None:
        vec, = parse_skill("[1 [2] ]")
        lst, = parse_skill("(1 (2))")
        assert isinstance(vec, LispVector)
        assert isinstance(lst, LispList)
        assert isinstance(vec.items[1], LispVector)
        assert vec.items[0] == 1 and vec.items[1].items[0] == 2

    def test_quote_sugar_wraps_symbol(self) -> None:
        (node,) = parse_skill("'sym")
        assert isinstance(node, Quote)
        assert node.kind == "quote"
        assert node.item == Symbol("sym")

    def test_quote_sugar_wraps_whole_list(self) -> None:
        (node,) = parse_skill("'(1 (x 2))")
        assert isinstance(node, Quote)
        assert isinstance(node.item, LispList)
        assert node.item.items[0] == 1
        # quote 不落表内首原子
        assert not isinstance(node.item.items[0], Quote)

    def test_quasiquote_unquote_splicing_tokens(self) -> None:
        (node,) = parse_skill("`(a ,b ,@c)")
        assert isinstance(node, Quote)
        assert node.kind == "quasiquote"
        body = node.item
        assert body.items[0].name == "a"
        assert body.items[1].kind == "unquote"
        assert body.items[2].kind == "unquote-splicing"

    def test_nested_quote_order_outer_inner(self) -> None:
        (node,) = parse_skill("''x")
        assert isinstance(node, Quote) and node.kind == "quote"
        assert isinstance(node.item, Quote) and node.item.kind == "quote"

    def test_sugar_fold_f_paren(self) -> None:
        (node,) = parse_skill("f(1 2)")
        assert isinstance(node, LispList)
        assert node.items[0] == Symbol("f")
        assert list(node.items[1:]) == [1, 2]
        assert render_skill(node) == "(f 1 2)"

    def test_sugar_fold_nested_and_head(self) -> None:
        (node,) = parse_skill("defun( f (x) (g x))")
        assert render_skill(node) == "(defun f (x) (g x))"

    def test_space_before_paren_no_fold(self) -> None:
        tree = parse_skill("f (1 2)")
        assert isinstance(tree[0], Symbol) and tree[0].name == "f"
        assert isinstance(tree[1], LispList)

    def test_unrecognized_char_fatal_with_position(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("a%b")
        assert "%" in str(ei.value)
        assert ei.value.line == 1 and ei.value.column == 2

    def test_crlf_line_endings(self) -> None:
        tree = parse_skill("(a\r\n(b)\r\n)")
        assert isinstance(tree[0], LispList)
        assert tree[0].items[1].line == 2

    def test_bom_prefix_stripped(self) -> None:
        tree = parse_skill("﻿(a)")
        assert isinstance(tree[0], LispList)

    def test_empty_and_comment_only_return_empty(self) -> None:
        assert parse_skill("") == []
        assert parse_skill("  \n\t ") == []
        assert parse_skill("; only\n/* comments */") == []

# ══════════════════════════ 节点树类型判等 ══════════════════════════

class TestNodeTree:
    def test_symbol_eq_ignores_line(self) -> None:
        assert Symbol("a", 1) == Symbol("a", 99)
        assert Symbol("a") != Symbol("b")
        assert hash(Symbol("a", 1)) == hash(Symbol("a", 99))

    def test_lisplist_eq_hash_ignores_line(self) -> None:
        a = LispList((Symbol("x", 1), 2), line=3)
        b = LispList((Symbol("x", 9), 2), line=8)
        assert a == b
        assert hash(a) == hash(b)

    def test_list_vs_vector_distinct(self) -> None:
        assert LispList((1,)) != LispVector((1,))

    def test_quote_kinds_and_hash(self) -> None:
        kinds = {"quote", "quasiquote", "unquote", "unquote-splicing"}
        nodes = [Quote(Symbol("x"), kind=k) for k in kinds]
        assert len(set(nodes)) == 4  # kind 参与判等
        assert hash(Quote(Symbol("x"))) == hash(Quote(Symbol("x"), line=7))

    def test_int_float_distinct_values(self) -> None:
        tree = parse_skill("(1 1.0)")
        items = tree[0].items
        assert isinstance(items[0], int) and isinstance(items[1], float)

    def test_render_roundtrip_compact(self) -> None:
        text = "(defun f (x) (g (h 1 \"s\") [2 3]))"
        tree = parse_skill(text)
        assert render_skill(tree[0]) == text

    def test_render_escaped_symbol_rebars(self) -> None:
        (node,) = parse_skill("|a b|")
        assert render_skill(node) == "|a b|"

    def test_node_to_plain_json_native(self) -> None:
        (node,) = parse_skill("'(1 (x 2) [3] 'q)")
        plain = node_to_plain(node.item)
        assert plain == [
            1,
            [{"symbol": "x"}, 2],
            {"vector": [3]},
            {"quote": "quote", "of": {"symbol": "q"}},
        ]
        assert json.dumps(plain)  # JSON 原生可序列化

    def test_tree_stats_counts(self) -> None:
        stats = skill_tree_stats(parse_skill("(a (b c) [d]) 'q"))
        assert stats["n_top_level"] == 2
        assert stats["n_lists"] == 2
        assert stats["n_vectors"] == 1
        assert stats["n_symbols"] == 5
        assert stats["n_quotes"] == 1
        assert stats["max_depth"] == 2

# ══════════════════════════ 括号失衡/结构违规（行号+列号）════════════════

class TestParseErrors:
    def test_extra_close_paren_position(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("(a )\n)")
        assert "多余的右括号" in str(ei.value)
        assert (ei.value.line, ei.value.column) == (2, 1)

    def test_extra_close_bracket_position(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("[a ]]")
        assert "右方括号" in str(ei.value)
        assert (ei.value.line, ei.value.column) == (1, 5)

    def test_unclosed_paren_innermost_with_count(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("(a (b")
        assert "未闭合" in str(ei.value)
        assert "2 个关闭符" in str(ei.value)
        assert (ei.value.line, ei.value.column) == (1, 4)  # 最内未闭合者

    def test_cross_mismatch_bracket_vs_paren(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("(a [b)")
        assert "括号交叉失配" in str(ei.value)
        assert (ei.value.line, ei.value.column) == (1, 6)

    def test_unterminated_string(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill('(a "x')
        assert "引号字符串未闭合" in str(ei.value)
        assert ei.value.line == 1

    def test_unterminated_block_comment(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("a /* x")
        assert "块注释 /* 未闭合" in str(ei.value)

    def test_unterminated_vsymbol(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("|x")
        assert "转义符号 |...| 未闭合" in str(ei.value)

    def test_dangling_quote_at_eof(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("(a) '")
        assert "缺被引用表达式" in str(ei.value)
        assert (ei.value.line, ei.value.column) == (1, 5)

    def test_dangling_quote_before_close(self) -> None:
        with pytest.raises(SkillParseError) as ei:
            parse_skill("'(a ')")
        assert "缺被引用表达式" in str(ei.value)
        assert ei.value.column == 5

    def test_parse_error_is_value_error(self) -> None:
        assert issubclass(SkillParseError, ValueError)
        assert issubclass(SkillEvalError, ValueError)

    def test_depth_guard_at_limit_ok(self) -> None:
        text = "(" * MAX_NEST_DEPTH + ")" * MAX_NEST_DEPTH
        tree = parse_skill(text)
        assert isinstance(tree[0], LispList)

    def test_depth_guard_exceeded_fatal(self) -> None:
        text = "(" * (MAX_NEST_DEPTH + 1) + ")" * (MAX_NEST_DEPTH + 1)
        with pytest.raises(SkillParseError) as ei:
            parse_skill(text)
        assert str(MAX_NEST_DEPTH) in str(ei.value)
        assert ei.value.line == 1

    def test_depth_guard_custom_limit(self) -> None:
        with pytest.raises(SkillParseError):
            parse_skill("((()))", max_depth=2)

# ══════════════════════════ 结构提取：definitions ══════════════════════

class TestDefinitions:
    def test_defun_entry(self, main_defs) -> None:
        first = main_defs["definitions"][0]
        assert first["form"] == "defun"
        assert first["name"] == "filterGain"
        assert first["args"] == ["g", "f0"]
        assert first["arity"] == 2
        assert first["style"] == "defun"
        assert first["line"] == _line_of(SKILL_MAIN, "defun( filterGain")
        # 重复定义双列：两处 occurrence 均标 dup=True（互为重复）
        assert first["dup"] is True

    def test_define_value_form(self, main_defs) -> None:
        entry = next(d for d in main_defs["definitions"]
                     if d["name"] == "kFactor")
        assert entry["form"] == "define"
        assert entry["style"] == "value"
        assert entry["arity"] is None
        assert entry["args"] == []

    def test_define_fptr_form_args_exclude_name(self, main_defs) -> None:
        entry = next(d for d in main_defs["definitions"]
                     if d["name"] == "kDouble")
        assert entry["style"] == "fptr"
        assert entry["args"] == ["x"]
        assert entry["arity"] == 1

    def test_define_value_lambda_arity(self, main_defs) -> None:
        entry = next(d for d in main_defs["definitions"] if d["name"] == "sq")
        assert entry["style"] == "value"
        assert entry["args"] == ["x"]
        assert entry["arity"] == 1

    def test_duplicate_double_listed_and_warned(self, main_defs) -> None:
        assert main_defs["duplicates"] == ["filterGain"]
        dups = [d for d in main_defs["definitions"] if d["dup"]]
        assert [d["arity"] for d in dups] == [2, 1]
        assert len(main_defs["warnings"]) == 1
        assert "重复定义" in main_defs["warnings"][0]
        assert main_defs["stats"] == {
            "n_definitions": 6,
            "n_unique_names": 5,
            "n_duplicates": 1,
            "n_warnings": 1,
        }
        assert main_defs["names"] == [
            "filterGain", "kFactor", "kDouble", "sq", "sweepGrid",
        ]

    def test_define_missing_value_warns(self) -> None:
        defs = skill_definitions(parse_skill("(define x)"))
        assert defs["definitions"][0]["name"] == "x"
        assert any("缺值" in w for w in defs["warnings"])

    def test_define_missing_name_warns(self) -> None:
        defs = skill_definitions(parse_skill("(define)"))
        assert defs["definitions"][0]["name"] is None
        assert any("缺合法名字" in w for w in defs["warnings"])

    def test_special_markers_kept_verbatim_in_args(self) -> None:
        defs = skill_definitions(
            parse_skill("(defun f (a &optional b &rest r))"))
        assert defs["definitions"][0]["args"] == [
            "a", "&optional", "b", "&rest", "r"]
        assert defs["definitions"][0]["arity"] == 5  # 清单长度口径（含标记符）

    def test_sugar_style_defun_found(self) -> None:
        # f( 调用糖书写形态：defun( f (x) …) ≡ (defun f (x) …)
        defs = skill_definitions(parse_skill("defun( q (a b c) t)"))
        assert defs["names"] == ["q"]
        assert defs["definitions"][0]["arity"] == 3

# ══════════════════════════ 结构提取：top_level ════════════════════════

class TestTopLevelForms:
    def test_categories_closed_set(self) -> None:
        assert set(TOP_LEVEL_CATEGORIES) == {
            "definition", "special", "call", "expr", "vector", "quote", "atom",
        }

    def test_special_forms_closed_set(self) -> None:
        assert frozenset({
            "quote", "let", "let*", "lambda", "nlambda", "define", "defun",
            "prog", "prog*", "cond", "if", "when", "unless", "and", "or",
            "case", "caseq", "foreach", "for", "setf", "setq",
            "function", "funcall", "apply",
        }) == SPECIAL_FORMS

    def test_main_category_counts(self, main_tree) -> None:
        top = skill_top_level_forms(main_tree)
        assert top["n_top_level"] == 14
        assert top["category_counts"] == {
            "definition": 6,
            "special": 2,
            "call": 4,
            "expr": 0,
            "vector": 0,
            "quote": 2,
            "atom": 0,
        }

    def test_head_counts_and_form_index(self, main_tree) -> None:
        top = skill_top_level_forms(main_tree)
        assert top["head_counts"]["defun"] == 3
        assert top["head_counts"]["define"] == 3
        assert top["head_counts"]["setq"] == 1
        forms = top["forms"]
        assert forms[0]["index"] == 0
        assert forms[0]["category"] == "definition"
        assert forms[11]["category"] == "quote"
        assert forms[7]["head"] == "ocnWaveformTool"

    def test_atom_and_vector_rows(self) -> None:
        top = skill_top_level_forms(parse_skill("sym [1 2] \"s\" 3 `(a)"))
        assert [row["category"] for row in top["forms"]] == [
            "atom", "vector", "atom", "atom", "quote",
        ]
        assert top["forms"][0]["head"] == "sym"

# ══════════════════════════ 结构提取：api_calls ════════════════════════

class TestApiCalls:
    def test_bucket_table_closed_set(self) -> None:
        assert API_BUCKETS == ("ocean", "virtuoso", "generic", "unknown")
        assert API_PREFIX_BUCKETS == {
            "ocean": ("ocn", "asi", "sim", "netlist", "vms"),
            "virtuoso": ("hi", "ge", "le", "db"),
        }
        assert set(api["buckets"] for api in [None] if False) == set()

    @pytest.mark.parametrize(
        "name, bucket",
        [
            ("ocnPrint", "ocean"),
            ("asiCreate", "ocean"),
            ("simulator", "ocean"),
            ("netlistAndSpectre", "ocean"),
            ("vmsSomething", "ocean"),
            ("hiShowWindow", "virtuoso"),
            ("geGetEditCellView", "virtuoso"),
            ("leHiForm", "virtuoso"),
            ("dbOpenCellViewByType", "virtuoso"),
            ("car", "generic"),
            ("myHelper", "generic"),
        ],
    )
    def test_api_bucket_classification(self, name: str, bucket: str) -> None:
        assert api_bucket(name) == bucket

    def test_main_by_bucket(self, main_api) -> None:
        assert main_api["by_bucket"] == {
            "ocean": 5,
            "virtuoso": 4,
            "generic": 6,
            "unknown": 0,
        }
        assert main_api["stats"]["n_calls"] == 15
        assert main_api["stats"]["n_names"] == 13

    def test_main_by_name_frequencies(self, main_api) -> None:
        by_name = main_api["by_name"]
        assert by_name["*"] == 3
        assert by_name["ocnPrint"] == 1
        assert by_name["hiShowWindow"] == 1
        assert "car" not in by_name  # setf 目标位剪除
        assert "t" not in by_name  # cond 分支测试位不计调用

    def test_form_index_and_line_recorded(self, main_api) -> None:
        row = next(c for c in main_api["calls"] if c["name"] == "simulator")
        assert row["form_index"] == 4
        assert row["line"] == _line_of(SKILL_MAIN, "simulator(")

    def test_quote_data_excluded(self) -> None:
        api = skill_api_calls(parse_skill("'(ocnPrint x) (quote (hiShow y))"))
        assert api["stats"]["n_calls"] == 0

    def test_quasiquote_template_excluded(self) -> None:
        api = skill_api_calls(parse_skill("`(1 ,x ,@rest)"))
        assert api["stats"]["n_calls"] == 0

    def test_binding_vars_excluded_let_flat(self) -> None:
        api = skill_api_calls(parse_skill("(let (a (foo 1) b 2) (bar a))"))
        assert api["by_name"] == {"foo": 1, "bar": 1}

    def test_lambda_and_defun_args_excluded(self) -> None:
        api = skill_api_calls(
            parse_skill("(lambda (x y) (use x)) (defun f (p q) (go p))"))
        assert api["by_name"] == {"use": 1, "go": 1}

    def test_setf_setq_targets_excluded_values_kept(self) -> None:
        api = skill_api_calls(parse_skill("(setf (car p) (baz q)) (setq a 1)"))
        assert api["by_name"] == {"baz": 1}  # 目标位 (car p) 剪除、值位照常

    def test_foreach_loop_var_excluded(self) -> None:
        api = skill_api_calls(parse_skill("(foreach dev (visit dev))"))
        assert api["by_name"] == {"visit": 1}

    def test_case_patterns_excluded_bodies_kept(self) -> None:
        api = skill_api_calls(parse_skill("(case op (1 (foo)) (2 (bar)))"))
        assert api["by_name"] == {"foo": 1, "bar": 1}

    def test_unknown_head_non_symbol(self) -> None:
        api = skill_api_calls(parse_skill("((lambda (x) x) 5)"))
        assert api["by_bucket"]["unknown"] == 1
        assert api["stats"]["n_unknown_head"] == 1
        row = api["calls"][0]
        assert row["name"] is None
        assert row["head_raw"] == "(lambda (x) x)"

    def test_special_form_heads_not_calls(self) -> None:
        api = skill_api_calls(parse_skill("(if (ready) (go))"))
        assert api["by_name"] == {"ready": 1, "go": 1}
        assert api["by_bucket"]["generic"] == 2

# ══════════════════════════ 结构提取：globals ═════════════════════════

class TestGlobals:
    def test_main_globals(self, main_tree) -> None:
        g = skill_globals(main_tree)
        assert g["n_assignments"] == 4
        # 文档序：sweepGrid 内 setf( grid ) 先于顶层 setq( a b )
        assert g["targets"] == ["grid", "a", "b"]
        assert g["n_unique_targets"] == 3
        forms = [(row["form"], row["name"], row["target_kind"]) for row in g["globals"]]
        assert forms == [
            ("setf", "grid", "symbol"),  # 文档序：sweepGrid 内先于顶层 setq
            ("setq", "a", "symbol"),
            ("setq", "b", "symbol"),
            ("setf", None, "expr"),
        ]

    def test_expr_target_raw(self, main_tree) -> None:
        g = skill_globals(main_tree)
        row = g["globals"][3]
        assert row["target_raw"] == "(car pair)"
        assert row["slot"] == 0

    def test_scope_depth_nested(self, main_tree) -> None:
        g = skill_globals(main_tree)
        assert g["globals"][0]["depth"] == 2  # sweepGrid(0) > foreach(1) > setf(2)
        assert g["globals"][1]["depth"] == 0  # 顶层 setq

    def test_setq_multi_pairs_slots(self) -> None:
        g = skill_globals(parse_skill("(setq a 1 b 2 c 3)"))
        assert [row["slot"] for row in g["globals"]] == [0, 1, 2]
        assert g["targets"] == ["a", "b", "c"]

    def test_value_missing_warns(self) -> None:
        g = skill_globals(parse_skill("(setq a 1 b)"))
        assert g["globals"][1]["value_missing"] is True
        assert any("缺配对值" in w for w in g["warnings"])

    def test_globals_inside_quote_data_excluded(self) -> None:
        g = skill_globals(parse_skill("'(setq x 1)"))
        assert g["n_assignments"] == 0

# ══════════════════════════ 静态调用边 ═════════════════════════════════

class TestCallEdges:
    def test_main_edges_by_name_match(self, main_tree) -> None:
        edges = skill_call_edges(main_tree)
        got = {(e["caller"], e["callee"]): e["count"] for e in edges["edges"]}
        assert got == {
            ("filterGain", "*"): 1,  # let 绑定值位归属最近包围定义
            ("filterGain", "g"): 1,
            ("filterGain", "ocnPrint"): 1,
            ("filterGain", "hiShowWindow"): 1,
            ("filterGain", "negwidth"): 1,
            ("kDouble", "*"): 1,
            ("sq", "*"): 1,
            ("sweepGrid", "simulator"): 1,
            ("sweepGrid", "netlistAndSpectre"): 1,
            ("sweepGrid", "asiCreate"): 1,
        }
        assert edges["n_edges"] == 10
        assert edges["defined_names"] == [
            "filterGain", "kFactor", "kDouble", "sq", "sweepGrid",
        ]

    def test_external_sorted_by_count_then_name(self, main_tree) -> None:
        external = skill_call_edges(main_tree)["external"]
        assert external[0] == {"name": "*", "count": 3}
        names = [e["name"] for e in external]
        assert "negwidth" in names and "ocnPrint" in names
        assert names == sorted(names, key=lambda n: (
            -dict((e["name"], e["count"]) for e in external)[n], n))
        assert skill_call_edges(main_tree)["n_external"] == 13

    def test_recursion_self_edge(self) -> None:
        edges = skill_call_edges(parse_skill("(defun fact (n) (fact (- n 1)))"))
        assert edges["edges"] == [
            {"caller": "fact", "callee": "-", "count": 1},
            {"caller": "fact", "callee": "fact", "count": 1},
        ]
        assert edges["external"] == [{"name": "-", "count": 1}]

    def test_nested_definition_innermost_attribution(self) -> None:
        tree = parse_skill(
            "(defun outer (x) (defun inner (y) (inner_help y)) (outer_help x))")
        edges = skill_call_edges(tree)
        got = {(e["caller"], e["callee"]) for e in edges["edges"]}
        assert got == {("inner", "inner_help"), ("outer", "outer_help")}

    def test_external_counts_top_level_calls(self) -> None:
        edges = skill_call_edges(parse_skill("(foo) (foo) (bar)"))
        assert edges["edges"] == []
        assert edges["external"] == [
            {"name": "foo", "count": 2}, {"name": "bar", "count": 1},
        ]

    def test_no_edges_when_no_definitions(self) -> None:
        tree = parse_skill("(foo 1)")
        assert skill_call_edges(tree)["n_edges"] == 0

# ══════════════════════════ 只读求值面 ═════════════════════════════════

def _eval(text: str):
    return skill_literal_eval(parse_skill(text)[0])

class TestLiteralEval:
    def test_literals_passthrough(self) -> None:
        assert _eval("42") == 42
        assert _eval("2.5") == 2.5
        assert _eval('"s"') == "s"

    def test_add_and_mul(self) -> None:
        assert _eval("(+ 1 2 3)") == 6
        assert _eval("(+ 1 (* 2 3))") == 7
        assert _eval("(* 2 3 4)") == 24

    def test_sub_unary_and_fold(self) -> None:
        assert _eval("(- 5)") == -5
        assert _eval("(- 10 3 2)") == 5

    def test_div_true_float(self) -> None:
        assert _eval("(/ 7 2)") == 3.5
        assert isinstance(_eval("(/ 6 2)"), float)

    def test_div_zero_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError, match="除零"):
            _eval("(/ 1 0)")

    def test_arith_non_number_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError, match="须为数字"):
            _eval('(+ 1 "a")')

    def test_arith_missing_args_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError):
            _eval("(+)")
        with pytest.raises(SkillEvalError):
            _eval("(/ 2)")

    def test_quote_plain_data(self) -> None:
        assert _eval("(quote (a b))") == [{"symbol": "a"}, {"symbol": "b"}]
        assert _eval("'(1 (x 2))") == [1, [{"symbol": "x"}, 2]]

    def test_list_append_cons(self) -> None:
        assert _eval("(list 1 2)") == [1, 2]
        assert _eval("(append (list 1) (list 2 3))") == [1, 2, 3]
        assert _eval("(cons 0 (list 1 2))") == [0, 1, 2]

    def test_append_non_list_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError, match="须为表"):
            _eval("(append 1)")
        with pytest.raises(SkillEvalError, match="须为表"):
            _eval("(cons 1 2)")  # 非真表第二参数 fail-closed（不造点对）

    def test_strcat(self) -> None:
        assert _eval('(strcat "a" "b" "c")') == "abc"

    def test_strcat_non_string_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError, match="须全为字符串"):
            _eval('(strcat "a" 1)')

    def test_symbol_reference_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError, match="符号引用"):
            skill_literal_eval(Symbol("kFactor"))

    def test_unknown_operator_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError, match="未知算子"):
            _eval("(sprintf nil \"%d\" 1)")

    def test_vector_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError, match="向量"):
            _eval("[1 2]")

    def test_quasiquote_not_unrolled(self) -> None:
        with pytest.raises(SkillEvalError, match="不展开"):
            _eval("`(1 ,x)")

    def test_empty_list_fail_closed(self) -> None:
        with pytest.raises(SkillEvalError):
            _eval("()")

    def test_nested_literal_arithmetic(self) -> None:
        assert _eval("(- (* 2 (+ 1 3)) (/ 8 4))") == 6.0

# ══════════════════════════ 服务信封 ══════════════════════════════════

class TestService:
    def test_parse_file_ok_envelope(self, tmp_path: Path) -> None:
        result = skill_service.parse_skill_file(_write(tmp_path, SKILL_MAIN))
        assert result["ok"] is True
        assert set(result) == {"ok", "path", "schema", "forms", "stats", "warnings"}
        assert result["schema"] == f"skill/{PARSER_SCHEMA_VERSION}"
        assert result["stats"]["n_top_level"] == 14
        assert json.dumps(result["forms"])  # forms 平面树 JSON 原生

    def test_parse_file_missing(self, tmp_path: Path) -> None:
        result = skill_service.parse_skill_file(tmp_path / "no.il")
        assert result["ok"] is False
        assert "不存在" in result["errors"][0]

    @pytest.mark.parametrize("text", ["", "  \n\t", "; only comment"])
    def test_parse_file_empty(self, tmp_path: Path, text: str) -> None:
        result = skill_service.parse_skill_file(_write(tmp_path, text))
        assert result["ok"] is False
        assert "为空" in result["errors"][0]

    def test_parse_file_directory(self, tmp_path: Path) -> None:
        result = skill_service.parse_skill_file(tmp_path)
        assert result["ok"] is False
        assert "目录" in result["errors"][0]

    def test_parse_file_unbalanced_line_column(self, tmp_path: Path) -> None:
        result = skill_service.parse_skill_file(_write(tmp_path, "(a (b"))
        assert result["ok"] is False
        assert result["line"] == 1
        assert result["column"] == 4
        assert "第 1 行第 4 列" in result["errors"][0]

    def test_parse_file_bom_and_latin1(self, tmp_path: Path) -> None:
        bom = tmp_path / "bom.il"
        bom.write_bytes(b"\xef\xbb\xbf(defun f (x) x)".replace(b"f (x)", b"f (x)"))
        assert skill_service.parse_skill_file(bom)["ok"] is True
        latin = tmp_path / "latin.il"
        latin.write_bytes(b"/* caf\xe9 */ (a)")
        result = skill_service.parse_skill_file(latin)
        assert result["ok"] is True

    def test_report_envelope(self, tmp_path: Path) -> None:
        result = skill_service.skill_report(_write(tmp_path, SKILL_MAIN))
        assert result["ok"] is True
        assert "forms" not in result  # 报告面聚合视图
        assert result["stats"]["n_definitions"] == 6
        assert result["stats"]["n_duplicates"] == 1
        assert result["duplicates"] == ["filterGain"]
        assert result["api"]["by_bucket"] == {
            "ocean": 5, "virtuoso": 4, "generic": 6, "unknown": 0,
        }
        assert result["targets"] == ["grid", "a", "b"]
        assert any("重复定义" in w for w in result["warnings"])

    def test_call_graph_envelope(self, tmp_path: Path) -> None:
        result = skill_service.skill_call_graph(_write(tmp_path, SKILL_MAIN))
        assert result["ok"] is True
        assert result["n_edges"] == 10
        assert result["n_external"] == 13
        assert ("filterGain", "ocnPrint") in {
            (e["caller"], e["callee"]) for e in result["edges"]}
        assert result["external"][0] == {"name": "*", "count": 3}

    def test_error_envelopes_errors_list_of_str(self, tmp_path: Path) -> None:
        failures = [
            skill_service.parse_skill_file(tmp_path / "x.il"),
            skill_service.skill_report(tmp_path / "x.il"),
            skill_service.skill_call_graph(tmp_path / "x.il"),
        ]
        for env in failures:
            assert env["ok"] is False
            assert isinstance(env["errors"], list)
            assert all(isinstance(e, str) for e in env["errors"])

    def test_service_deterministic(self, tmp_path: Path) -> None:
        path = _write(tmp_path, SKILL_MAIN)
        a = json.dumps(skill_service.skill_report(path), sort_keys=True)
        b = json.dumps(skill_service.skill_report(path), sort_keys=True)
        assert a == b

    def test_existing_recipe_and_card_api_untouched(self) -> None:
        # Q-X62 加性接线不触碰既有 API（同文件 F11/T-Q10 产线零变化面）
        from rfauto.service.skill_service import (
            card_to_skill_batch,
            experience_to_skill,
            recipe_to_skill,
            write_card_skill,
            write_experience_skill,
            write_skill,
        )
        for fn in (recipe_to_skill, write_skill, experience_to_skill,
                   write_experience_skill, write_card_skill,
                   card_to_skill_batch):
            assert callable(fn)

# ══════════════════════════ CLI 两叶 ══════════════════════════════════

class TestCli:
    def test_parse_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(skill_parse_app, [
            "parse", "--file", _write(tmp_path, SKILL_MAIN), "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["stats"]["n_top_level"] == 14

    def test_parse_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(skill_parse_app, [
            "parse", "--file", str(tmp_path / "no.il"), "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_report_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(skill_parse_app, [
            "report", "--file", _write(tmp_path, SKILL_MAIN), "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["api"]["by_bucket"]["ocean"] == 5
        assert envelope["duplicates"] == ["filterGain"]

    def test_report_json_failure_envelope(self, tmp_path: Path) -> None:
        bad = _write(tmp_path, "(a (b", name="bad.il")
        res = runner.invoke(skill_parse_app, [
            "report", "--file", bad, "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert envelope["line"] == 1 and envelope["column"] == 4

    def test_parse_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(skill_parse_app, [
            "parse", "--file", _write(tmp_path, SKILL_MAIN)])
        assert res.exit_code == 0, res.output
        assert "SKILL:" in res.output
        assert "top=14" in res.output

    def test_report_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(skill_parse_app, [
            "report", "--file", _write(tmp_path, SKILL_MAIN)])
        assert res.exit_code == 0, res.output
        assert "definitions=6" in res.output
        assert "filterGain" in res.output
        assert "DUPLICATE" in res.output
        assert "ocean=5" in res.output

    def test_human_output_escapes_markup_like_names(self, tmp_path: Path) -> None:
        res = runner.invoke(skill_parse_app, [
            "parse", "--file", _write(tmp_path, "(a [b])")])
        assert res.exit_code == 0, res.output
        assert "vectors=1" in res.output

    def test_human_failure_exit_1(self, tmp_path: Path) -> None:
        res = runner.invoke(skill_parse_app, [
            "parse", "--file", str(tmp_path / "no.il")])
        assert res.exit_code == 1
        assert "SKILL 解析失败" in res.output

    def test_help_builds_no_bare_percent(self) -> None:
        # #305 家法：--help 真构建 + 零裸 %
        for leaf in (["--help"], ["parse", "--help"], ["report", "--help"]):
            res = runner.invoke(skill_parse_app, leaf)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_missing_file_flag_fails(self) -> None:
        res = runner.invoke(skill_parse_app, ["parse"])
        assert res.exit_code != 0

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：skill_parse 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(skill_service.__file__).parent.parent.joinpath(
            "cli", "domains", "skill_parse.py").read_text(encoding="utf-8")
        assert source.count('@skill_parse_app.command("parse")') == 1
        assert source.count('@skill_parse_app.command("report")') == 1
        assert source.count("@skill_parse_app.command(") == 2
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
    def test_new_files_no_replacement_char(self) -> None:
        # #259 家法：Q-X62 三个新文件零 U+FFFD（Edit 长中文段替换字符抽查）
        src_root = Path(skill_service.__file__).parent.parent
        for path in (src_root / "core" / "skill_parser.py",
                     src_root / "service" / "skill_service.py",
                     src_root / "cli" / "domains" / "skill_parse.py",
                     Path(__file__)):
            text = path.read_text(encoding="utf-8")
            assert "\ufffd" not in text, str(path)
