"""STIL（IEEE 1450）解析内核+服务+CLI 薄壳单测（aurora_q Q-X72 席位）。

覆盖面（任务书 ≥60 条）：

- 词法/块状态机：注释双形态（/* */ 与 //）、字符串双引号形态、嵌套
  brace 平衡、深度守卫（100 层 OK/101 层 fatal）、未知顶层块整块 skip、
  顶层多余 } fail-soft、语句未以 ; 终结截断警告、行号进警告；
- 头部/身份面：header_version 提取、引号版本变体、空文件/纯注释/缺
  STIL 头/无版本 fail-closed（StilParseError=ValueError 子类）；
- Signals：4 信号方向+WFC 字符集回填（定义后置同样拿全集）、大小写归
  一、无 = 形态容忍、未知方向如实登记、重复名覆盖、病态语句跳过；
- SignalGroups：引号/无引号/级联（+ 剔除）/选择器（末个 : 之后）四形态、
  空组如实、重复名覆盖；
- Timing：WaveformTable 名+Period（引号/裸字）、waveforms 逐字符展开
  （01 → 0/1 共享事件表）、多语句事件扁平化、重复 wfc 后列覆盖、重复
  wft 后列覆盖、未知子块跳过；
- Pattern 面：burst 桶+声明语句空壳+内联体、向量行文件序、Loop 倍数
  累计（嵌套加和不乘积）、**大 Loop 不物化**（1000000 倍 vectors 仍 1
  行）、Shift/SubStroke 计数口径、Ann 收编（全域计数）、W 后列覆盖、
  fail-soft 跳行（长度不符/未知组）、两遍语义（Pattern 先于声明面）；
- 查询三函数：pattern_vectors 平坦清单+拷贝安全+未命中 None、
  vector_at 逐字符事件联查（缺映射/缺 wft/缺组 None 不猜、越界/负值
  None）、coverage 统计（覆盖组名录+覆盖率分数+空 patterns None）；
- 服务三函数信封契约（ok/error 两态、errors 恒 list[str]、不可读/空/
  无头/brace 失衡→error、Latin-1 兜底、detail 未命中带可用名录）；
- CLI（**stil_app 直连+局部父 Typer 自测**——共享 app 接线由主代合流统
  一，本席禁改 cli/main.py）：parse/report --json 全结构+human 紧凑面+
  失败信封同构（exit 1）+缺 --file usage 错（exit 2）+--help 真构建
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

from rfauto.cli.domains.stil import stil_app
from rfauto.core.stil_parser import (
    MAX_BLOCK_DEPTH,
    PARSER_SCHEMA_VERSION,
    SIGNAL_DIRECTIONS,
    StilParseError,
    parse_stil,
    stil_coverage_stats,
    stil_pattern_vectors,
    stil_vector_at,
)
from rfauto.service.stil_service import (
    parse_stil_file,
    stil_pattern_detail,
    stil_report,
)

# ── 主夹具（任务书口径：Signals 4+Groups 2+Timing 1 WFT 2 WFC 集+
#    PatternBurst 1+Pattern 2——其一含 Loop 3 与 Shift+长度不符向量行
#    fail-soft+Ann 注释）────────────────────────────────────────────────
# 预声明账（逐项断言）：
#   signals 4（clk/data/io/rst_n，wfcs 全 ['0','1']）
#   groups 2（grp_in=[clk,rst_n], grp_out=[data,io]）
#   timing 1 WFT（period 50ns；grp_in 0/1→['D']，grp_out 0/1→['C']）
#   patterns：burst1 下 p_seed（声明空壳）+p_loop（wft=main_wft）
#   p_loop 向量 5 行文件序：grp_in=01 / grp_out=LH / grp_in=10 /
#     grp_in=11 / grp_out=00；n_loop=3；n_shift=1；anns 2 条
#   警告恰 2 条（grp_in=000 长度 3≠2 跳行；ghost 未知组跳行）
#   stats：n_vectors_total=5, n_ann=2, n_loop_multiplier_total=3,
#     n_shift_total=1, n_vector_rows_skipped=2, n_unknown_blocks=0
SAMPLE_STIL = """\
STIL 1.0;

/* global wfc set: 0/1 */
Signals {
    clk = In;
    data = Out;
    io = InOut;
    rst_n = In;

    WFC_0 = '0';
    WFC_1 = '1';
}

SignalGroups {
    grp_in = 'clk rst_n';
    grp_out = 'data io';
}

Timing {
    WaveformTable main_wft {
        Period '50ns';
        Waveforms {
            grp_in {
                01 { 'D'; }
            }
            grp_out {
                01 { 'C'; }
            }
        }
    }
}

PatternBurst burst1 {
    PatternExec;
    Pattern p_seed;
    Pattern p_loop {
        W main_wft;
        Ann "shift in seed";
        V {
            grp_in = 01;
            grp_out = LH;
        }
        Loop 3 {
            V {
                grp_in = 10;
            }
            Shift {
                V {
                    grp_in = 11;
                    grp_out = 00;
                }
            }
        }
        V {
            grp_in = 000;
            ghost = 0101;
        }
        Ann "done";
    }
}
"""

PARSE_KEYS = {
    "ok", "path", "header_version", "signals", "groups", "timing",
    "patterns", "imports", "procedures", "pattern_execs", "stats",
    "warnings",
}
REPORT_KEYS = {
    "ok", "path", "header_version", "stats", "signals_summary",
    "groups_summary", "timing_summary", "patterns_summary", "warnings",
}
DETAIL_KEYS = {
    "ok", "path", "pattern", "burst", "wft", "vectors", "n_vectors",
    "n_loop", "n_shift", "anns", "warnings",
}

runner = CliRunner()

def _mini(body: str, head: str = "STIL 1.0;\n") -> dict[str, Any]:
    """最小头+正文 → 解析 doc（内联用例拼装器）。"""
    return parse_stil(head + body)

@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return parse_stil(SAMPLE_STIL)

@pytest.fixture(scope="module")
def stats(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["stats"]

@pytest.fixture()
def stil_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.stil"
    f.write_text(SAMPLE_STIL, encoding="utf-8")
    return f

@pytest.fixture(scope="module")
def local_app() -> typer.Typer:
    """局部父 Typer（共享 app 接线待主代合流；本席自测不经 cli/main）。"""
    parent = typer.Typer()
    parent.add_typer(stil_app, name="stil")
    return parent

# ── 身份面/词法（块状态机+注释双形态+行号）────────────────────────────

class TestIdentity:
    def test_header_version(self, doc: dict[str, Any]) -> None:
        assert doc["header_version"] == "1.0"

    def test_schema_tag(self, doc: dict[str, Any]) -> None:
        assert doc["schema"] == f"stil/{PARSER_SCHEMA_VERSION}"

    def test_quoted_version_variant(self) -> None:
        assert _mini("")["header_version"] == "1.0"
        d = parse_stil("STIL '1.0';\nSignals { a = In; }\n")
        assert d["header_version"] == "1.0"

    def test_empty_raises(self) -> None:
        with pytest.raises(StilParseError):
            parse_stil("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(StilParseError):
            parse_stil("  \n\t \r\n")

    def test_comment_only_raises(self) -> None:
        with pytest.raises(StilParseError):
            parse_stil("/* a */ // b\n")

    def test_missing_header_raises(self) -> None:
        with pytest.raises(StilParseError):
            parse_stil("Signals { a = In; }\n")

    def test_header_after_decls_ok(self) -> None:
        # 头部后置容忍（文件身份面只要求 STIL 头存在，不钉位置）
        d = parse_stil("Signals { a = In; }\nSTIL 1.0;\n")
        assert d["header_version"] == "1.0"

    def test_header_without_version_raises(self) -> None:
        with pytest.raises(StilParseError):
            parse_stil("STIL;\n")

    def test_error_is_value_error(self) -> None:
        assert issubclass(StilParseError, ValueError)

class TestLexer:
    def test_block_comment_stripped(self) -> None:
        d = _mini("/* head note */ Signals { /* inner */ a = In; }\n")
        assert d["signals"] == {"a": {"dir": "in", "wfcs": []}}
        assert d["warnings"] == []

    def test_line_comment_stripped(self) -> None:
        d = _mini("// lead\nSignals { a = In; // tail\n}\n")
        assert "a" in d["signals"]
        assert d["warnings"] == []

    def test_comment_line_numbers_advance(self) -> None:
        # 注释行号推进：注释占行后，警告行号仍指病态原文所在行
        # （_mini 头 "STIL 1.0;\n" 占第 1 行——x y z 在第 6 行）
        d = _mini("Signals {\n/* two\nline\ncomment */\nx y z;\n}\n")
        assert d["warnings"] == ["Signals 语句形态不识 'x y z'——跳过（第 6 行）"]

    def test_unterminated_block_comment_warns(self) -> None:
        d = _mini("/* never closed\n")
        assert any("块注释未闭合" in w for w in d["warnings"])

    def test_unterminated_string_warns(self) -> None:
        d = _mini('Import "abc\n')
        assert any("字符串引号未闭合" in w for w in d["warnings"])
        assert d["imports"] == ["abc"]

    def test_string_double_quote_form(self) -> None:
        d = _mini('Ann "hello world";\n')
        assert d["stats"]["n_ann"] == 1

    def test_stray_semicolons_silent(self) -> None:
        d = _mini(";;;\n")
        assert d["warnings"] == []

    def test_statement_without_semicolon_warns(self) -> None:
        d = _mini('Import "x.stil"')
        assert any("未以 ';'" in w for w in d["warnings"])

    def test_top_level_extra_close_warns(self) -> None:
        d = _mini("}\n")
        assert any("多余的 '}'" in w for w in d["warnings"])

    def test_nested_brace_balance(self) -> None:
        d = _mini("Signals { a = In; }\nX { Y { Z { } } }\n")
        assert d["stats"]["n_unknown_blocks"] == 1

# ── Signals / SignalGroups / Timing（声明面）──────────────────────────

class TestSignals:
    def test_signal_names(self, doc: dict[str, Any]) -> None:
        assert set(doc["signals"]) == {"clk", "data", "io", "rst_n"}

    def test_directions(self, doc: dict[str, Any]) -> None:
        dirs = {k: v["dir"] for k, v in doc["signals"].items()}
        assert dirs == {
            "clk": "in", "data": "out", "io": "inout", "rst_n": "in"}

    def test_wfc_set_backfilled(self, doc: dict[str, Any]) -> None:
        # WFC 定义在信号声明之后——全集回填不依赖相对顺序
        for sig in doc["signals"].values():
            assert sig["wfcs"] == ["0", "1"]

    def test_wfc_before_signals_same_set(self) -> None:
        d = _mini("Signals { WFC_0 = '0'; WFC_1 = '1'; a = In; }\n")
        assert d["signals"]["a"]["wfcs"] == ["0", "1"]

    def test_direction_case_normalized(self) -> None:
        d = _mini("Signals { a = IN; b = Out; }\n")
        assert d["signals"]["a"]["dir"] == "in"
        assert d["signals"]["b"]["dir"] == "out"

    def test_two_word_form_tolerated(self) -> None:
        d = _mini("Signals { a In; }\n")
        assert d["signals"]["a"]["dir"] == "in"
        assert d["warnings"] == []

    def test_unknown_direction_registered_as_is(self) -> None:
        d = _mini("Signals { b = Bidir; }\n")
        assert d["signals"]["b"]["dir"] == "bidir"
        assert any("方向 'bidir'" in w for w in d["warnings"])

    def test_duplicate_overwrite_warns(self) -> None:
        d = _mini("Signals { c = In; c = Out; }\n")
        assert d["signals"]["c"]["dir"] == "out"
        assert any("信号重复名 'c'" in w for w in d["warnings"])

    def test_malformed_statement_skipped(self) -> None:
        d = _mini("Signals { x y z w; a = In; }\n")
        assert set(d["signals"]) == {"a"}
        assert any("形态不识" in w for w in d["warnings"])

    def test_unknown_subblock_skipped(self) -> None:
        d = _mini("Signals { a = In; Foo { } }\n")
        assert any("未知子块 'Foo'" in w for w in d["warnings"])

    def test_direction_closed_set_constant(self) -> None:
        assert frozenset({"in", "out", "inout"}) == SIGNAL_DIRECTIONS

class TestGroups:
    def test_group_members(self, doc: dict[str, Any]) -> None:
        assert doc["groups"] == {
            "grp_in": ["clk", "rst_n"], "grp_out": ["data", "io"]}

    def test_concat_form(self) -> None:
        d = _mini("SignalGroups { a = 'x' + 'y'; }\n")
        assert d["groups"]["a"] == ["x", "y"]

    def test_selector_form(self) -> None:
        # '_sel': 'members' 形态取末个 : 之后的成员段
        d = _mini("SignalGroups { b = '_s': 'p q'; }\n")
        assert d["groups"]["b"] == ["p", "q"]
        assert d["warnings"] == []

    def test_unquoted_members(self) -> None:
        d = _mini("SignalGroups { c = m n; }\n")
        assert d["groups"]["c"] == ["m", "n"]

    def test_no_equals_form_tolerated(self) -> None:
        d = _mini("SignalGroups { d 'r s'; }\n")
        assert d["groups"]["d"] == ["r", "s"]
        assert any("缺 '='" in w for w in d["warnings"])

    def test_empty_group_registered_with_warning(self) -> None:
        d = _mini("SignalGroups { e = ''; }\n")
        assert d["groups"]["e"] == []
        assert any("成员列表为空" in w for w in d["warnings"])

    def test_duplicate_group_overwrite(self) -> None:
        d = _mini("SignalGroups { g = 'a'; g = 'b'; }\n")
        assert d["groups"]["g"] == ["b"]
        assert any("组重复名 'g'" in w for w in d["warnings"])

class TestTiming:
    def test_wft_name(self, doc: dict[str, Any]) -> None:
        assert list(doc["timing"]) == ["main_wft"]

    def test_period(self, doc: dict[str, Any]) -> None:
        assert doc["timing"]["main_wft"]["period"] == "50ns"

    def test_waveform_char_expansion(self, doc: dict[str, Any]) -> None:
        wf = doc["timing"]["main_wft"]["waveforms"]
        assert wf["grp_in"] == {"0": ["D"], "1": ["D"]}
        assert wf["grp_out"] == {"0": ["C"], "1": ["C"]}

    def test_missing_period_none(self) -> None:
        d = _mini("Timing { WaveformTable w { Waveforms { } } }\n")
        assert d["timing"]["w"]["period"] is None

    def test_period_bare_word(self) -> None:
        d = _mini("Timing { WaveformTable w { Period 100ns; } }\n")
        assert d["timing"]["w"]["period"] == "100ns"

    def test_multi_statement_events_flattened(self) -> None:
        d = _mini(
            "Timing { WaveformTable w { Waveforms { g { "
            "01 { 10 D; 20 U; } } } } }\n")
        assert d["timing"]["w"]["waveforms"]["g"] == {
            "0": ["10", "D", "20", "U"], "1": ["10", "D", "20", "U"]}

    def test_duplicate_wfc_overwrite_warns(self) -> None:
        d = _mini(
            "Timing { WaveformTable w { Waveforms { g { "
            "01 { 'D'; } 1 { 'U'; } } } } }\n")
        assert d["timing"]["w"]["waveforms"]["g"]["1"] == ["U"]
        assert any("重复定义" in w for w in d["warnings"])

    def test_duplicate_wft_overwrite_warns(self) -> None:
        d = _mini(
            "Timing { WaveformTable w { Period '1ns'; } "
            "WaveformTable w { Period '2ns'; } }\n")
        assert d["timing"]["w"]["period"] == "2ns"
        assert any("重复名 'w'" in w for w in d["warnings"])

    def test_unknown_subblocks_skipped(self) -> None:
        d = _mini("Timing { Foo x { } Bogus; WaveformTable w { Bar 1; } }\n")
        assert d["timing"]["w"]["period"] is None
        assert len(d["warnings"]) == 3

    def test_two_waveform_tables(self) -> None:
        d = _mini(
            "Timing { WaveformTable w1 { Period '1ns'; } "
            "WaveformTable w2 { Period '2ns'; } }\n")
        assert set(d["timing"]) == {"w1", "w2"}

# ── Pattern 面（burst/pattern/向量行/Loop/Shift/Ann）──────────────────

class TestPatterns:
    def test_patterns_under_burst(self, doc: dict[str, Any]) -> None:
        assert list(doc["patterns"]) == ["burst1"]
        assert list(doc["patterns"]["burst1"]["patterns"]) == [
            "p_seed", "p_loop"]

    def test_declared_only_pattern_shell(self, doc: dict[str, Any]) -> None:
        p = doc["patterns"]["burst1"]["patterns"]["p_seed"]
        assert p == {"wft": None, "vectors": [], "n_loop": 0, "n_shift": 0,
                     "anns": []}

    def test_pattern_wft(self, doc: dict[str, Any]) -> None:
        assert doc["patterns"]["burst1"]["patterns"]["p_loop"]["wft"] == (
            "main_wft")

    def test_vectors_file_order(self, doc: dict[str, Any]) -> None:
        assert doc["patterns"]["burst1"]["patterns"]["p_loop"]["vectors"] == [
            {"group": "grp_in", "values": "01"},
            {"group": "grp_out", "values": "LH"},
            {"group": "grp_in", "values": "10"},
            {"group": "grp_in", "values": "11"},
            {"group": "grp_out", "values": "00"},
        ]

    def test_loop_and_shift_counts(self, doc: dict[str, Any]) -> None:
        p = doc["patterns"]["burst1"]["patterns"]["p_loop"]
        assert p["n_loop"] == 3
        assert p["n_shift"] == 1

    def test_anns_collected(self, doc: dict[str, Any]) -> None:
        assert doc["patterns"]["burst1"]["patterns"]["p_loop"]["anns"] == [
            "shift in seed", "done"]

    def test_stats_totals(self, stats: dict[str, Any]) -> None:
        assert stats == {
            "n_signals": 4, "n_groups": 2, "n_patterns": 2,
            "n_vectors_total": 5, "n_ann": 2, "n_bursts": 1, "n_wfts": 1,
            "n_loop_multiplier_total": 3, "n_shift_total": 1,
            "n_vector_rows_skipped": 2, "n_unknown_blocks": 0,
            "n_warnings": 2,
        }

    def test_skip_warnings_with_lines(self, doc: dict[str, Any]) -> None:
        assert doc["warnings"] == [
            "向量行 'grp_in' 值串长度 3 ≠ 组员数 2——跳行（第 55 行）",
            "向量行引用未知组 'ghost'（可用组: grp_in, grp_out）"
            "——跳行（第 56 行）",
        ]

    def test_top_level_pattern_empty_burst(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p_top { W w1; V { g = 0; } }\n")
        assert list(d["patterns"]) == [""]
        assert d["patterns"][""]["patterns"]["p_top"]["vectors"] == [
            {"group": "g", "values": "0"}]

    def test_burst_statement_declaration_warns(self) -> None:
        # PatternBurst 无体声明语句：零 pattern 如实 + fail-soft 警告
        d = _mini("PatternBurst b;\n")
        assert d["patterns"] == {}
        assert any("未知语句 'PatternBurst'" in w for w in d["warnings"])

    def test_nested_loop_additive(self) -> None:
        # Loop 倍数累计和（嵌套加和不乘积——不物化口径）
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { Loop 2 { Loop 4 { V { g = 0; } } } }\n")
        assert d["patterns"][""]["patterns"]["p"]["n_loop"] == 6

    def test_loop_multiplier_edge_cases(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { Loop 0 { V { g = 0; } } "
                  "Loop x { V { g = 1; } } Loop { V { g = 0; } } }\n")
        assert d["patterns"][""]["patterns"]["p"]["n_loop"] == 3
        assert len(d["warnings"]) == 3

    def test_big_loop_not_materialized(self) -> None:
        # 大 Loop 不炸内存：倍数只进 stats，向量行不物化展开
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { Loop 1000000 { V { g = 1; } } }\n")
        p = d["patterns"][""]["patterns"]["p"]
        assert p["n_loop"] == 1000000
        assert len(p["vectors"]) == 1

    def test_substroke_silent(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { SubStroke { V { g = 1; } } }\n")
        assert d["warnings"] == []
        assert d["patterns"][""]["patterns"]["p"]["vectors"] == [
            {"group": "g", "values": "1"}]

    def test_w_last_wins(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { W w1; W w2; }\n")
        assert d["patterns"][""]["patterns"]["p"]["wft"] == "w2"

    def test_unknown_pattern_items_warn(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { Foo { } Bogus 1; }\n")
        assert any("未知子块 'Foo'" in w for w in d["warnings"])
        assert any("未知语句 'Bogus'" in w for w in d["warnings"])

    def test_duplicate_pattern_in_burst(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "PatternBurst b { Pattern x; Pattern x { } }\n")
        assert list(d["patterns"]["b"]["patterns"]) == ["x"]
        assert any("Pattern 重复名 'x'" in w for w in d["warnings"])

    def test_duplicate_burst_overwrite(self) -> None:
        d = _mini("PatternBurst b { Pattern x; }\n"
                  "PatternBurst b { Pattern y; }\n")
        assert list(d["patterns"]["b"]["patterns"]) == ["y"]
        assert any("PatternBurst 重复名 'b'" in w for w in d["warnings"])

    def test_same_pattern_name_in_two_bursts(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "PatternBurst b1 { Pattern p { V { g = 0; } } }\n"
                  "PatternBurst b2 { Pattern p { V { g = 1; } } }\n")
        assert list(d["patterns"]) == ["b1", "b2"]
        # 查询取 burst 插入序首个命中——确定性
        assert stil_pattern_vectors(d, "p") == [{"group": "g", "values": "0"}]

    def test_top_level_ann_counted(self) -> None:
        d = _mini('Ann "top";\nAnn \'two\';\n')
        assert d["stats"]["n_ann"] == 2
        assert d["patterns"] == {}

# ── 向量行 fail-soft / 两遍语义 ───────────────────────────────────────

class TestVectorRows:
    def test_quoted_values_whitespace_stripped(self) -> None:
        d = _mini("Signals { a = In; b = In; }\nSignalGroups { g = 'a b'; }\n"
                  "Pattern p { V { g = '0 1'; } }\n")
        assert d["patterns"][""]["patterns"]["p"]["vectors"] == [
            {"group": "g", "values": "01"}]

    def test_mismatch_row_skipped(self, doc: dict[str, Any]) -> None:
        # 长度不符跳行：不入 vectors、进 stats、警告带行号（主夹具已验）
        assert doc["stats"]["n_vector_rows_skipped"] == 2

    def test_unknown_group_hint_lists_available(self, doc) -> None:
        assert any("'ghost'" in w and "grp_in, grp_out" in w
                   for w in doc["warnings"])

    def test_two_word_row_tolerated(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { V { g '1'; } }\n")
        assert d["patterns"][""]["patterns"]["p"]["vectors"] == [
            {"group": "g", "values": "1"}]
        assert any("缺 '='" in w for w in d["warnings"])

    def test_unknown_subblock_in_v_warns(self) -> None:
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n"
                  "Pattern p { V { g = 0; Foo { } } }\n")
        assert any("未知子块 'Foo'" in w for w in d["warnings"])

    def test_two_pass_pattern_before_decls(self) -> None:
        # Pattern 块先于 Signals/SignalGroups/Timing——两遍语义仍全解析
        d = parse_stil(
            "STIL 1.0;\n"
            "Pattern p_top { W w1; V { g = 01; } }\n"
            "Signals { a = In; b = In; }\n"
            "SignalGroups { g = 'a b'; }\n"
            "Timing { WaveformTable w1 { Waveforms { g { 01 { 'D'; } } } } }\n")
        p = d["patterns"][""]["patterns"]["p_top"]
        assert p["vectors"] == [{"group": "g", "values": "01"}]
        assert d["warnings"] == []
        row = stil_vector_at(d, "p_top", 0)
        assert row is not None and row["events"] == [["D"], ["D"]]

# ── 查询三函数+覆盖统计 ────────────────────────────────────────────────

class TestQueries:
    def test_pattern_vectors_flat(self, doc: dict[str, Any]) -> None:
        assert stil_pattern_vectors(doc, "p_loop") == [
            {"group": "grp_in", "values": "01"},
            {"group": "grp_out", "values": "LH"},
            {"group": "grp_in", "values": "10"},
            {"group": "grp_in", "values": "11"},
            {"group": "grp_out", "values": "00"},
        ]

    def test_pattern_vectors_miss_none(self, doc: dict[str, Any]) -> None:
        assert stil_pattern_vectors(doc, "nope") is None

    def test_pattern_vectors_declared_empty(self, doc: dict[str, Any]) -> None:
        assert stil_pattern_vectors(doc, "p_seed") == []

    def test_pattern_vectors_copy_safe(self, doc: dict[str, Any]) -> None:
        rows = stil_pattern_vectors(doc, "p_loop")
        assert rows is not None
        rows[0]["values"] = "MUTATED"
        rows.append({"group": "x", "values": "y"})
        assert doc["patterns"]["burst1"]["patterns"]["p_loop"]["vectors"][0][
            "values"] == "01"
        assert len(doc["patterns"]["burst1"]["patterns"]["p_loop"][
            "vectors"]) == 5

    def test_vector_at_events_join(self, doc: dict[str, Any]) -> None:
        assert stil_vector_at(doc, "p_loop", 0) == {
            "pattern": "p_loop", "index": 0, "group": "grp_in",
            "values": "01", "wft": "main_wft", "events": [["D"], ["D"]]}

    def test_vector_at_missing_wfc_mapping_none(self, doc) -> None:
        # grp_out=LH：wft 波形表只有 0/1——L/H 缺映射如实 None 不猜
        assert stil_vector_at(doc, "p_loop", 1) == {
            "pattern": "p_loop", "index": 1, "group": "grp_out",
            "values": "LH", "wft": "main_wft", "events": [None, None]}

    def test_vector_at_out_of_range_none(self, doc: dict[str, Any]) -> None:
        assert stil_vector_at(doc, "p_loop", 5) is None

    def test_vector_at_negative_none(self, doc: dict[str, Any]) -> None:
        assert stil_vector_at(doc, "p_loop", -1) is None

    def test_vector_at_unknown_pattern_none(self, doc: dict[str, Any]) -> None:
        assert stil_vector_at(doc, "ghost_p", 0) is None

    def test_vector_at_no_wft_all_none(self) -> None:
        d = _mini("Signals { a = In; b = In; }\nSignalGroups { g = 'a b'; }\n"
                  "Pattern q { V { g = 00; } }\n")
        row = stil_vector_at(d, "q", 0)
        assert row is not None
        assert row["wft"] is None and row["events"] == [None, None]

    def test_vector_at_unknown_wft_all_none(self) -> None:
        d = _mini("Signals { a = In; b = In; }\nSignalGroups { g = 'a b'; }\n"
                  "Pattern r { W ghost; V { g = 00; } }\n")
        row = stil_vector_at(d, "r", 0)
        assert row is not None
        assert row["wft"] == "ghost" and row["events"] == [None, None]

    def test_vector_at_partial_mapping(self) -> None:
        # 波形表只定义 0——X 字符缺映射混排如实 [None 兼 [D]]
        d = _mini("Signals { a = In; b = In; }\nSignalGroups { g = 'a b'; }\n"
                  "Timing { WaveformTable w { Waveforms { g { "
                  "0 { 'D'; } } } } }\n"
                  "Pattern p { W w; V { g = 0X; } }\n")
        row = stil_vector_at(d, "p", 0)
        assert row is not None and row["events"] == [["D"], None]

class TestCoverage:
    def test_rows_insertion_order(self, doc: dict[str, Any]) -> None:
        cov = stil_coverage_stats(doc)
        assert cov["patterns"] == [
            {"burst": "burst1", "pattern": "p_seed", "n_vectors": 0,
             "n_loop": 0, "n_shift": 0, "groups_covered": [],
             "n_groups_covered": 0},
            {"burst": "burst1", "pattern": "p_loop", "n_vectors": 5,
             "n_loop": 3, "n_shift": 1,
             "groups_covered": ["grp_in", "grp_out"], "n_groups_covered": 2},
        ]

    def test_totals(self, doc: dict[str, Any]) -> None:
        cov = stil_coverage_stats(doc)
        assert cov["n_patterns"] == 2
        assert cov["n_groups_total"] == 2
        assert cov["n_groups_covered_distinct"] == 2
        assert cov["covered_groups"] == ["grp_in", "grp_out"]
        assert cov["coverage_fraction"] == 1.0

    def test_partial_fraction(self) -> None:
        d = _mini("Signals { a = In; b = In; }\n"
                  "SignalGroups { g1 = 'a'; g2 = 'b'; }\n"
                  "Pattern p { V { g1 = 0; } }\n")
        cov = stil_coverage_stats(d)
        assert cov["coverage_fraction"] == 0.5
        assert cov["covered_groups"] == ["g1"]

    def test_no_patterns_fraction_zero(self) -> None:
        # 无 patterns：覆盖率 0.0 如实（未覆盖任何组）；fraction None 仅
        # 无组退化态（分数无定义）
        d = _mini("Signals { a = In; }\nSignalGroups { g = 'a'; }\n")
        cov = stil_coverage_stats(d)
        assert cov["patterns"] == []
        assert cov["n_patterns"] == 0
        assert cov["coverage_fraction"] == 0.0

    def test_no_groups_fraction_none(self) -> None:
        d = _mini("PatternBurst b { Pattern p; }\n")
        cov = stil_coverage_stats(d)
        assert cov["n_groups_total"] == 0
        assert cov["coverage_fraction"] is None

# ── fail-soft/fatal 面 + 确定性 ────────────────────────────────────────

class TestFatalAndFailSoft:
    def test_unclosed_brace_fatal_with_line(self) -> None:
        with pytest.raises(StilParseError) as ei:
            parse_stil("STIL 1.0;\nSignals {\n  a = In;\n")
        assert "第 2 行" in str(ei.value)
        assert "brace 失衡" in str(ei.value)

    def test_nested_unclosed_brace_fatal(self) -> None:
        with pytest.raises(StilParseError) as ei:
            parse_stil("STIL 1.0;\nSignals { a = In; }\n"
                       "Pattern p {\n V {\n g = 0;\n}\n")
        assert "第 3 行" in str(ei.value)

    def test_depth_guard_ok_at_limit(self) -> None:
        d = _mini("X {" * MAX_BLOCK_DEPTH + "}" * MAX_BLOCK_DEPTH + "\n")
        assert d["stats"]["n_unknown_blocks"] == 1

    def test_depth_guard_fatal_beyond_limit(self) -> None:
        with pytest.raises(StilParseError) as ei:
            _mini("X {" * (MAX_BLOCK_DEPTH + 1) + "}" * (MAX_BLOCK_DEPTH + 1)
                  + "\n")
        assert "深度守卫" in str(ei.value)

    def test_unknown_block_skipped_whole(self) -> None:
        d = _mini("UnknownBlk x { deep { y = 1; } 'str'; }\n"
                  "Signals { a = In; }\n")
        assert d["stats"]["n_unknown_blocks"] == 1
        assert set(d["signals"]) == {"a"}
        assert any("未知顶层块 'UnknownBlk'" in w for w in d["warnings"])

    def test_deterministic(self) -> None:
        assert parse_stil(SAMPLE_STIL) == parse_stil(SAMPLE_STIL)

    def test_json_round_trip(self, doc: dict[str, Any]) -> None:
        assert json.loads(json.dumps(doc, ensure_ascii=False)) == doc

    def test_json_safe_envelope_contract(self) -> None:
        # 统计键恒整数（JSON 原生类型——信封零序列化意外面）
        d = _mini("Signals { a = In; }\n")
        assert all(isinstance(v, int) for v in d["stats"].values())

# ── Import / Procedures / PatternExec（如实登记面）─────────────────────

class TestRegistry:
    def test_import_registered(self, doc: dict[str, Any]) -> None:
        d = _mini('Import "bsdl_ref.stil";\n')
        assert d["imports"] == ["bsdl_ref.stil"]

    def test_procedures_names_registered(self) -> None:
        d = _mini("Procedures { init_p { WFT w; V { g = 0; } } load { } }\n")
        assert d["procedures"] == ["init_p", "load"]
        assert d["warnings"] == []

    def test_pattern_exec_refs(self) -> None:
        d = _mini("PatternExec pe { PatternBurst b1; Protocol pr; }\n")
        assert d["pattern_execs"] == {
            "pe": {"pattern_burst": "b1", "protocol": "pr"}}

    def test_pattern_exec_unknown_stmt_warns(self) -> None:
        d = _mini("PatternExec pe { Bogus z; }\n")
        assert d["pattern_execs"]["pe"]["pattern_burst"] is None
        assert any("'Bogus'" in w for w in d["warnings"])

    def test_pattern_exec_in_burst(self) -> None:
        d = _mini("PatternBurst b { PatternExec; Pattern p; }\n")
        assert list(d["patterns"]["b"]["patterns"]) == ["p"]
        assert d["warnings"] == []

# ── 服务三函数（AU-2 信封契约）─────────────────────────────────────────

class TestService:
    def test_parse_ok_envelope_keys(self, stil_file: Path) -> None:
        r = parse_stil_file(stil_file)
        assert r["ok"] is True
        assert set(r) == PARSE_KEYS
        assert r["path"] == str(stil_file)
        assert r["stats"]["n_vectors_total"] == 5

    def test_parse_envelope_json_safe(self, stil_file: Path) -> None:
        json.dumps(parse_stil_file(stil_file), ensure_ascii=False)  # 不抛即过

    def test_parse_unreadable_error(self, tmp_path: Path) -> None:
        r = parse_stil_file(tmp_path / "no_such.stil")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert "不可读" in r["errors"][0]

    def test_parse_empty_file_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.stil"
        f.write_text("", encoding="utf-8")
        r = parse_stil_file(f)
        assert r["ok"] is False
        assert "解析失败" in r["errors"][0]

    def test_parse_no_header_error(self, tmp_path: Path) -> None:
        f = tmp_path / "nohead.stil"
        f.write_text("Signals { a = In; }\n", encoding="utf-8")
        r = parse_stil_file(f)
        assert r["ok"] is False
        assert "STIL" in r["errors"][0]

    def test_parse_brace_imbalance_error_with_line(self, tmp_path: Path) -> None:
        f = tmp_path / "imbalance.stil"
        f.write_text("STIL 1.0;\nSignals {\n  a = In;\n", encoding="utf-8")
        r = parse_stil_file(f)
        assert r["ok"] is False
        assert "第 2 行" in r["errors"][0]

    def test_report_envelope(self, stil_file: Path) -> None:
        r = stil_report(stil_file)
        assert r["ok"] is True
        assert set(r) == REPORT_KEYS
        assert r["timing_summary"] == [
            {"name": "main_wft", "period": "50ns", "n_waveform_groups": 2}]
        assert r["patterns_summary"] == [
            {"burst": "burst1", "name": "p_seed", "wft": None,
             "n_vectors": 0, "n_loop": 0, "n_shift": 0},
            {"burst": "burst1", "name": "p_loop", "wft": "main_wft",
             "n_vectors": 5, "n_loop": 3, "n_shift": 1},
        ]
        assert r["signals_summary"][0] == {
            "name": "clk", "dir": "in", "wfcs": ["0", "1"]}
        assert r["groups_summary"] == [
            {"name": "grp_in", "members": ["clk", "rst_n"]},
            {"name": "grp_out", "members": ["data", "io"]},
        ]

    def test_report_unreadable_error(self, tmp_path: Path) -> None:
        r = stil_report(tmp_path / "missing.stil")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)

    def test_detail_found(self, stil_file: Path) -> None:
        r = stil_pattern_detail(stil_file, "p_loop")
        assert r["ok"] is True
        assert set(r) == DETAIL_KEYS
        assert r["burst"] == "burst1"
        assert r["n_vectors"] == 5
        assert r["n_loop"] == 3
        assert r["n_shift"] == 1
        assert r["anns"] == ["shift in seed", "done"]
        assert len(r["vectors"]) == 5

    def test_detail_declared_empty_pattern(self, stil_file: Path) -> None:
        r = stil_pattern_detail(stil_file, "p_seed")
        assert r["ok"] is True
        assert r["vectors"] == [] and r["n_vectors"] == 0

    def test_detail_miss_lists_available(self, stil_file: Path) -> None:
        r = stil_pattern_detail(stil_file, "ghost_p")
        assert r["ok"] is False
        assert "ghost_p" in r["errors"][0]
        assert "burst1.p_seed" in r["errors"][0]
        assert "burst1.p_loop" in r["errors"][0]

    def test_detail_unreadable_error(self, tmp_path: Path) -> None:
        r = stil_pattern_detail(tmp_path / "missing.stil", "p")
        assert r["ok"] is False
        assert "不可读" in r["errors"][0]

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.stil"
        f.write_bytes(b"STIL 1.0;\nAnn \"caf\xe9 note\";\n")
        r = parse_stil_file(f)
        assert r["ok"] is True
        assert r["stats"]["n_ann"] == 1

    def test_service_deterministic(self, stil_file: Path) -> None:
        assert parse_stil_file(stil_file) == parse_stil_file(stil_file)

# ── CLI（stil_app 直连/局部父 Typer 自测；接线待合流）──────────────────

class TestCli:
    def test_parse_json_envelope(self, local_app: typer.Typer,
                                 stil_file: Path) -> None:
        r = runner.invoke(local_app, ["stil", "parse", "--file",
                                      str(stil_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert set(payload) == PARSE_KEYS
        assert payload["stats"]["n_vectors_total"] == 5

    def test_parse_human_output(self, local_app: typer.Typer,
                                stil_file: Path) -> None:
        r = runner.invoke(local_app, ["stil", "parse", "--file",
                                      str(stil_file)])
        assert r.exit_code == 0, r.output
        assert "clk" in r.output and "grp_in" in r.output
        assert "4" in r.output  # signals=4 汇总行

    def test_parse_failure_json_exit1(self, local_app: typer.Typer,
                                      tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["stil", "parse", "--file",
                                      str(tmp_path / "nope.stil"), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert len(payload["errors"]) == 1

    def test_parse_failure_human_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["stil", "parse", "--file",
                                      str(tmp_path / "nope.stil")])
        assert r.exit_code == 1
        assert "STIL 解析失败" in r.output

    def test_parse_missing_file_option_exit2(self,
                                             local_app: typer.Typer) -> None:
        r = runner.invoke(local_app, ["stil", "parse"])
        assert r.exit_code == 2

    def test_report_json_envelope(self, local_app: typer.Typer,
                                  stil_file: Path) -> None:
        r = runner.invoke(local_app, ["stil", "report", "--file",
                                      str(stil_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert set(payload) == REPORT_KEYS
        assert payload["patterns_summary"][1]["n_vectors"] == 5

    def test_report_human_output(self, local_app: typer.Typer,
                                 stil_file: Path) -> None:
        r = runner.invoke(local_app, ["stil", "report", "--file",
                                      str(stil_file)])
        assert r.exit_code == 0, r.output
        assert "main_wft" in r.output
        assert "p_loop" in r.output

    def test_report_failure_json_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["stil", "report", "--file",
                                      str(tmp_path / "nope.stil"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_report_failure_human_exit1(self, local_app: typer.Typer,
                                        tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["stil", "report", "--file",
                                      str(tmp_path / "nope.stil")])
        assert r.exit_code == 1
        assert "STIL 报告失败" in r.output

    @pytest.mark.parametrize("leaf", ["parse", "report"])
    def test_help_real_build(self, local_app: typer.Typer, leaf: str) -> None:
        # #305：真构建 --help（帮助串含 % 或裸 [ 会在展开期炸/渲染歪）
        r = runner.invoke(local_app, ["stil", leaf, "--help"])
        assert r.exit_code == 0, r.output
        assert "--file" in r.output

    def test_direct_app_help(self) -> None:
        r = runner.invoke(stil_app, ["--help"])
        assert r.exit_code == 0, r.output
        assert "parse" in r.output and "report" in r.output

    def test_domain_leaf_shape(self, local_app: typer.Typer) -> None:
        from typer.main import get_command

        group = get_command(local_app).commands.get("stil")
        assert group is not None
        assert set(group.commands) == {"parse", "report"}

    def test_help_text_hygiene(self, local_app: typer.Typer) -> None:
        # D-06 门同判定面预检：命令 help/short_help 与参数 help 零裸 [、
        # 零未成对 %（合流后进全树门亦绿）
        from typer.main import get_command

        group = get_command(local_app).commands["stil"]
        texts = [group.help or ""]
        for cmd in group.commands.values():
            texts.extend([cmd.help or "", cmd.short_help or ""])
            texts.extend(getattr(p, "help", None) or "" for p in cmd.params)
        for text in texts:
            assert "[" not in text, text
            assert text.replace("%%", "").count("%") == 0, text

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：stil 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(
            __import__("rfauto.service.stil_service", fromlist=["x"])
            .__file__).parent.parent.joinpath(
            "cli", "domains", "stil.py").read_text(encoding="utf-8")
        assert source.count('@stil_app.command("parse")') == 1
        assert source.count('@stil_app.command("report")') == 1
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
