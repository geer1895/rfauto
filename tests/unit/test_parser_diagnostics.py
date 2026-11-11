"""AX-6 解析器 tier 分层诊断单测（aurora_r R-02 席位，2026-11-10）。

覆盖面：

- 共享工具（core/parser_diagnostics）：tier 词表闭集/make_parse_diagnostic
  形状与非法 tier ValueError/line_snippet 原文不美化（#331：前导空白
  保留、行尾换行剥除）/diagnostics_summary 全四档恒列+非法 tier 计数；
- SPEF 接入：未知指令=tier1/未知单位=tier3/方向词表外=tier3/病态值行=
  unparsed；clean 样本 diagnostics 恒空；每事件六键齐全+parser=spef；
- SPICE 接入：未知元件首字母=tier1/元件令牌不足（条目降级登记）=tier3/
  X 引用外部未定义子电路=tier2/X 缺子电路名=unparsed/Spectre 形态
  master 兜底归档=tier3；warnings 文案零变化（substring 同在）；
- Spectre 接入：无法归类=unparsed/后缀语义矛盾 value_si=None=tier3/
  lang=spice 外语段=tier1/预处理条件=tier2/缺 lang 声明=tier3/未闭合
  subckt=tier3；summary 聚合与事件序；
- 服务信封附加键：三解析面 parse 信封 diagnostics 键在档（纯增量），
  report 信封 diagnostics_summary 聚合在档。

单测零网络零真机；文件面一律 tmp_path（#144 run 湖零写入）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rfauto.core.parser_diagnostics import (
    DIAGNOSTIC_SCHEMA_VERSION,
    TIER_UNPARSED,
    TIER_UNSUPPORTED_1,
    TIER_UNSUPPORTED_2,
    TIER_UNSUPPORTED_3,
    TIER_VALUES,
    diagnostics_summary,
    line_snippet,
    make_parse_diagnostic,
)
from rfauto.core.spectre_parser import parse_spectre_text
from rfauto.core.spef_parser import parse_spef
from rfauto.core.spice_netlist_parser import parse_spice_netlist_text
from rfauto.service.spectre_service import parse_spectre_file
from rfauto.service.spef_service import parse_spef_file, spef_report
from rfauto.service.spice_netlist_service import parse_netlist_text

# ── 共享工具 ────────────────────────────────────────────────────────────


class TestSharedToolkit:
    def test_tier_wordlist_closed(self) -> None:
        assert {
            "unparsed", "unsupported-tier1", "unsupported-tier2",
            "unsupported-tier3",
        } == TIER_VALUES
        assert TIER_UNPARSED == "unparsed"
        assert TIER_UNSUPPORTED_1 == "unsupported-tier1"
        assert TIER_UNSUPPORTED_2 == "unsupported-tier2"
        assert TIER_UNSUPPORTED_3 == "unsupported-tier3"

    def test_make_parse_diagnostic_shape(self) -> None:
        d = make_parse_diagnostic(TIER_UNPARSED, "some_reason", 12, "  raw line  ",
                                  parser="spef")
        assert d == {
            "schema": f"parse_diagnostic/{DIAGNOSTIC_SCHEMA_VERSION}",
            "tier": "unparsed",
            "parser": "spef",
            "reason": "some_reason",
            "line": 12,
            "snippet": "  raw line  ",
        }

    def test_invalid_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="不在词表"):
            make_parse_diagnostic("tier9", "r", 1, "s", parser="spef")

    def test_line_snippet_preserves_original(self) -> None:
        # #331 不美化：前导空白/行内内容逐字保留，仅剥行尾换行
        assert line_snippet("  keep  me \r\n") == "  keep  me "
        assert line_snippet("no_newline") == "no_newline"

    def test_summary_all_tiers_listed(self) -> None:
        diags = [
            make_parse_diagnostic(TIER_UNPARSED, "a", 1, "x", parser="spef"),
            make_parse_diagnostic(TIER_UNPARSED, "b", 2, "y", parser="spef"),
            make_parse_diagnostic(TIER_UNSUPPORTED_3, "c", 3, "z", parser="spef"),
        ]
        s = diagnostics_summary(diags)
        assert s["n_total"] == 3
        assert s["by_tier"] == {
            "unparsed": 2, "unsupported-tier1": 0,
            "unsupported-tier2": 0, "unsupported-tier3": 1,
        }
        assert s["n_invalid_tier"] == 0

    def test_summary_invalid_tier_counted(self) -> None:
        rogue = {"tier": "bogus", "reason": "r"}
        s = diagnostics_summary([rogue])
        assert s["n_total"] == 1
        assert s["n_invalid_tier"] == 1

    def test_summary_empty(self) -> None:
        s = diagnostics_summary([])
        assert s["n_total"] == 0
        assert set(s["by_tier"]) == set(TIER_VALUES)


# ── SPEF 接入 ───────────────────────────────────────────────────────────

_SPEF_HEAD = '*SPEF "IEEE 1481-1998"\n*C_UNIT 1 PF\n'


class TestSpefDiagnostics:
    def test_unknown_instruction_is_tier1(self) -> None:
        d = parse_spef(_SPEF_HEAD + "*FOO bar\n")
        tiers = [(x["tier"], x["reason"]) for x in d["diagnostics"]]
        assert (TIER_UNSUPPORTED_1, "unknown_instruction") in tiers
        # 既有 warnings 文案零变化（substring 契约同在）
        assert any("未知指令 *FOO" in w for w in d["warnings"])

    def test_unknown_unit_is_tier3(self) -> None:
        d = parse_spef('*SPEF "x"\n*C_UNIT 1 ZZ\n')
        assert any(
            x["tier"] == TIER_UNSUPPORTED_3
            and x["reason"] == "unknown_unit_factor_defaults_1"
            for x in d["diagnostics"])

    def test_port_direction_out_of_vocabulary_is_tier3(self) -> None:
        d = parse_spef(_SPEF_HEAD + "*PORTS\na X\n")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_3
            and x["reason"] == "port_direction_out_of_vocabulary"
            for x in d["diagnostics"])

    def test_cap_bad_value_is_unparsed_with_reason(self) -> None:
        d = parse_spef(_SPEF_HEAD + "*D_NET *1 0\n*CAP\n1 a abc\n*END\n")
        assert any(
            x["tier"] == TIER_UNPARSED and x["reason"] == "unrecognized"
            and x["line"] == 5 and x["snippet"] == "1 a abc"
            for x in d["diagnostics"])

    def test_every_diagnostic_has_full_shape(self) -> None:
        d = parse_spef(_SPEF_HEAD + "*D_NET *1 0\n*CAP\n1 a abc\n*END\n"
                       "*PORTS\nb X\n")
        assert d["diagnostics"], "预置事件缺失"
        for x in d["diagnostics"]:
            assert set(x) == {"schema", "tier", "parser", "reason", "line",
                              "snippet"}
            assert x["parser"] == "spef"
            assert x["tier"] in TIER_VALUES

    def test_clean_sample_has_empty_diagnostics(self) -> None:
        d = parse_spef(_SPEF_HEAD + "*D_NET *1 1.0\n*CAP\n1 a 0.5\n*END\n")
        assert d["diagnostics"] == []
        assert d["warnings"] == []


# ── SPICE 接入 ──────────────────────────────────────────────────────────


class TestSpiceDiagnostics:
    def test_unknown_letter_is_tier1(self) -> None:
        # 首行恒为标题（SPICE 惯例）——未知首字母行须在标题行之后
        d = parse_spice_netlist_text("title\n@1 a b 1k\n.end\n", "ngspice")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_1
            and x["reason"] == "element_letter_unsupported"
            and x["line"] == 2 and "@1" in (x["snippet"] or "")
            for x in d["diagnostics"])

    def test_element_token_shortage_is_tier3(self) -> None:
        d = parse_spice_netlist_text(
            "title\nR1 only_one_node\n.end\n", "ngspice")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_3
            and x["reason"] == "element_insufficient_tokens_degraded"
            for x in d["diagnostics"])

    def test_x_unresolved_reference_is_tier2(self) -> None:
        d = parse_spice_netlist_text(
            "title\nX1 a b ghost_sub\n.end\n", "ngspice")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_2
            and x["reason"] == "x_reference_unresolved_external"
            for x in d["diagnostics"])

    def test_x_missing_ref_is_unparsed(self) -> None:
        # 括号 pin 形态无尾随子电路名 → 缺引用（X1 a b 的尾词会被当引用，
        # 走未定义引用 tier2 面——两形态如实分诊）
        d = parse_spice_netlist_text("title\nX1 (a b)\n.end\n", "ngspice")
        assert any(
            x["tier"] == TIER_UNPARSED and x["reason"] == "x_missing_subckt_ref"
            for x in d["diagnostics"])

    def test_spectre_master_fallback_is_tier3(self) -> None:
        text = "mmain (a b) weirdmaster w=1u\n"
        d = parse_spice_netlist_text(text, "spectre")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_3
            and x["reason"] == "master_first_letter_fallback"
            for x in d["diagnostics"])

    def test_warnings_text_unchanged_alongside(self) -> None:
        # 结构化诊断是附加层——既有 warning/structural_errors 文案零变化
        d = parse_spice_netlist_text("title\nQ1 a b c\n.end\n", "ngspice")
        assert any("令牌不足" in e for e in d["structural_errors"])
        assert any(
            x["reason"] == "element_insufficient_tokens_degraded"
            for x in d["diagnostics"])

    def test_clean_deck_empty_diagnostics(self) -> None:
        d = parse_spice_netlist_text(
            "RC divider\nV1 in 0 DC 5\nR1 in out 1k\nR2 out 0 2k\n.end\n",
            "ngspice")
        assert d["diagnostics"] == []


# ── Spectre 接入 ────────────────────────────────────────────────────────


class TestSpectreDiagnostics:
    def test_unclassifiable_is_unparsed(self) -> None:
        d = parse_spectre_text("simulator lang=spectre\n$$$ junk $$$\n")
        assert any(
            x["tier"] == TIER_UNPARSED
            and x["reason"] == "statement_unclassifiable"
            for x in d["diagnostics"])

    def test_ambiguous_suffix_is_tier3(self) -> None:
        d = parse_spectre_text(
            "simulator lang=spectre\nr1 (a b) resistor r=2M\n")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_3
            and x["reason"] == "suffix_ambiguous_value_si_none"
            for x in d["diagnostics"])

    def test_foreign_language_segment_is_tier1(self) -> None:
        d = parse_spectre_text(
            "simulator lang=spectre\nsimulator lang=spice\nR1 a b 1k\n")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_1
            and x["reason"] == "foreign_language_segment"
            for x in d["diagnostics"])

    def test_preprocessor_conditional_is_tier2(self) -> None:
        d = parse_spectre_text(
            "simulator lang=spectre\n#ifdef FAST\nr1 (a b) resistor r=1\n#endif\n")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_2
            and x["reason"] == "preprocessor_conditional_not_evaluated"
            for x in d["diagnostics"])

    def test_missing_lang_is_tier3(self) -> None:
        d = parse_spectre_text("r1 (a b) resistor r=1\n")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_3
            and x["reason"] == "missing_lang_declaration_assumed"
            for x in d["diagnostics"])

    def test_unclosed_subckt_is_tier3(self) -> None:
        d = parse_spectre_text(
            "simulator lang=spectre\nsubckt amp (a b)\nr1 (a b) resistor r=1\n")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_3
            and x["reason"] == "subckt_unclosed_at_eof"
            for x in d["diagnostics"])

    def test_undefined_subckt_reference_is_tier2(self) -> None:
        d = parse_spectre_text(
            "simulator lang=spectre\nx1 (a b) external_block\n")
        assert any(
            x["tier"] == TIER_UNSUPPORTED_2
            and x["reason"] == "subckt_reference_undefined_external"
            for x in d["diagnostics"])

    def test_summary_over_spectre_doc(self) -> None:
        d = parse_spectre_text(
            "simulator lang=spectre\n$$$ junk $$$\n"
            "subckt amp (a b)\nr1 (a b) resistor r=1\n")
        s = diagnostics_summary(d["diagnostics"])
        assert s["n_total"] == len(d["diagnostics"])
        assert s["by_tier"]["unparsed"] >= 1
        assert s["by_tier"]["unsupported-tier3"] >= 1


# ── 服务信封附加键 ──────────────────────────────────────────────────────


class TestServiceEnvelopeDiagnostics:
    @pytest.fixture()
    def spef_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "d.spef"
        f.write_text(
            _SPEF_HEAD + "*D_NET *1 0\n*CAP\n1 a abc\n*END\n",
            encoding="utf-8")
        return f

    @pytest.fixture()
    def spectre_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "d.scs"
        f.write_text(
            "simulator lang=spectre\n$$$ junk $$$\n", encoding="utf-8")
        return f

    def test_spef_parse_envelope_has_diagnostics(
            self, spef_file: Path) -> None:
        r = parse_spef_file(spef_file)
        assert r["ok"] is True
        assert isinstance(r["diagnostics"], list)
        assert r["diagnostics"], "病态值行事件应在档"

    def test_spef_report_envelope_has_summary(self, spef_file: Path) -> None:
        r = spef_report(spef_file)
        assert r["ok"] is True
        assert r["diagnostics_summary"]["n_total"] == len(r["diagnostics"])

    def test_spice_envelope_has_diagnostics_and_summary(self) -> None:
        r = parse_netlist_text("title\n@1 a b 1k\n.end\n", "ngspice")
        assert r["ok"] is True
        assert any(x["reason"] == "element_letter_unsupported"
                   for x in r["diagnostics"])
        assert r["diagnostics_summary"]["by_tier"][
            "unsupported-tier1"] == 1

    def test_spectre_envelope_has_diagnostics(
            self, spectre_file: Path) -> None:
        r = parse_spectre_file(spectre_file)
        assert r["ok"] is True
        assert any(x["reason"] == "statement_unclassifiable"
                   for x in r["diagnostics"])

    def test_diag_events_json_safe(self, spef_file: Path) -> None:
        r = parse_spef_file(spef_file)
        json.dumps(r["diagnostics"])  # 全 JSON 原生类型

    def test_fact_layer_immutable_spef(self, spef_file: Path) -> None:
        # 事实层不可变：诊断构建不触碰 parse 输出（深比较）
        doc = parse_spef(_SPEF_HEAD + "*D_NET *1 0\n*CAP\n1 a abc\n*END\n")
        frozen = copy.deepcopy(doc)
        diagnostics_summary(doc["diagnostics"])
        assert doc == frozen
