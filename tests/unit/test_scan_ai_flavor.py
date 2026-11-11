"""T-Q1（aurora_q Q-W5-1）：去 AI 味机械化扫描器自钉。

钉四类：
1. 词面判定：C1/C2/C7/C8 检出 + 上下文/短语/剥除豁免不误报；
2. 白名单机制：缘由列必填（validate_whitelist 形态纪律）+ 路径/行/子串匹配；
3. 机械面：py 字符串字面量层（注释不进判定面）+ md 逐行 + i18n 值逐键；
4. 集成棘轮：四新面+i18n 在当前树净命中=0（词汇层只收不放；结构类判据
   仍归 docs/style/ui-copy-humanize.md 人工面）。

判据母本：docs/style/ui-copy-humanize.md（K1 守则）R2/R3/R14/R15；
CLI 树同款词表棘轮=tests/unit/test_cli_help_text_hygiene.py
TestHelpCopyBlacklist（两器判定面互补不重叠）。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER_PATH = REPO_ROOT / "scripts" / "scan_ai_flavor.py"


def _load_scanner():
    """按文件路径装载扫描器（scripts/ 非包，check_numbers 同款 importlib 模式）。"""
    spec = importlib.util.spec_from_file_location("_scan_ai_flavor", SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_scan_ai_flavor", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sf():
    return _load_scanner()


# ─── 1. 词表不可变钉 ────────────────────────────────────────────────────────

class TestVocabImmutability:
    """词表=tuple 只收不放（命中=疑似清单，词表本体守 K1 守则 R2/R15）。"""

    def test_vocab_are_tuples(self, sf):
        for vocab in (sf.ZH_BLACKLIST, sf.ZH_TAILS, sf.EN_BLACKLIST, sf.ZH_CALLOUT,
                      sf.PHRASE_EXEMPT):
            assert isinstance(vocab, tuple), "词表必须不可变 tuple（棘轮只收不放）"

    def test_key_members_present(self, sf):
        # 任务书点名的真命中词与守则 R2/R15 代表词必须在册
        for w in ("一站式", "赋能", "抓手", "一目了然", "深耕", "海量",
                  "无缝", "完美", "卓越", "极致", "保驾护航"):
            assert w in sf.ZH_BLACKLIST
        for w in ("seamless", "empower", "leverag", "comprehensive",
                  "one-stop", "all-in-one", "helps you"):
            assert w in sf.EN_BLACKLIST
        assert "帮助你" in sf.ZH_TAILS
        assert "的你" in sf.ZH_CALLOUT

    def test_documented_out_words_absent(self, sf):
        # 闭环/一键：控制回路/单命令技术义为主，CLI 棘轮同裁决（留守则人工面）；
        # robust/harness/unlock：工程语境合法（robustness_report/gt_unlocked）
        for w in ("闭环", "一键"):
            assert w not in sf.ZH_BLACKLIST
        for w in ("robust", "harness", "unlock", "powerful", "various", "easily"):
            assert w not in sf.EN_BLACKLIST

    def test_whitelist_entries_have_reason(self, sf):
        """白名单缘由列必填（现行 WHITELIST 形态钉 + 校验器负例钉）。"""
        sf.validate_whitelist()  # 现行条目全部带 reason，不抛
        for entry in sf.WHITELIST:
            assert entry.get("reason"), f"白名单条目缺缘由：{entry}"
            assert entry.get("path")

    def test_whitelist_validation_rejects_missing_reason(self, sf, monkeypatch):
        bad = ({"path": "x.md"},)
        monkeypatch.setattr(sf, "WHITELIST", bad)
        with pytest.raises(ValueError, match="reason"):
            sf.validate_whitelist()

    def test_whitelist_validation_rejects_unknown_key(self, sf, monkeypatch):
        bad = ({"path": "x.md", "reason": "r", "whoops": 1},)
        monkeypatch.setattr(sf, "WHITELIST", bad)
        with pytest.raises(ValueError, match="未知键"):
            sf.validate_whitelist()


# ─── 2. 词面判定（检出+豁免）───────────────────────────────────────────────

class TestMatchLine:
    def test_c1_zhit_detected(self, sf):
        assert sf._match_line("EDB 建库与 Touchstone 导出一站式编排") == [
            ("C1", "一站式")]

    def test_c2_c7_c8_detected(self, sf):
        assert ("C2", "帮助你") in sf._match_line("一键帮助你快速上手")
        assert ("C7", "seamless") in sf._match_line("Seamlessly integrate everything")
        assert ("C8", "的你") in sf._match_line("写给第一次接触 rfauto 的你")

    def test_en_prefix_match_captures_inflections(self, sf):
        for text in ("empowers users", "leveraging data", "effortless setup",
                     "streamlined flow", "cutting-edge tools"):
            assert sf._match_line(text), text

    def test_context_exempts_rf_semantics(self, sf):
        # RF/数学"理想极限"技术语义不报（完美负载 Γ=0 / 完美镜像抑制 / CRLH 过渡）
        assert sf._match_line("None=完美镜像抑制") == []
        assert sf._match_line("完美负载 g=0 时窗塌缩") == []
        assert sf._match_line("平衡单元为 transition 无缝过渡点") == []
        assert sf._match_line("带边无缝衔接") == []
        # 短语豁免：KiCad seam 缝宽 / 文献题名引用
        assert sf._match_line('else "无缝宽事实来源"') == []
        assert sf._match_line("2025 无缝滤波——round19 来源清单") == []
        # 学科名/诚实免责义
        assert sf._match_line("缺省实现不假装智能") == []
        assert sf._match_line("智能体基准回归门") == []

    def test_marketing_semantics_still_red_after_exemptions(self, sf):
        # 豁免词不在行内时，营销义照常检出（豁免不放大成全词放行）
        assert ("C1", "完美") in sf._match_line("完美的用户体验")
        assert ("C1", "无缝") in sf._match_line("无缝接入一切设备")
        assert ("C1", "智能") in sf._match_line("智能的参数推荐")


# ─── 3. 机械面（py 字符串层/md/i18n）───────────────────────────────────────

class TestScanners:
    def test_py_string_layer_excludes_comments_and_identifiers(self, sf, tmp_path):
        p = tmp_path / "mod.py"
        p.write_text(
            '# 一站式 抓手（注释不进判定面）\n'
            '一站式 = "标识符不进判定面"\n'
            'def f():\n'
            '    """docstring 展示段一站式命中。"""\n',
            encoding="utf-8",
        )
        hits, stat = sf.scan_python_surface("mcp_docstring", [p])
        words = {h.word for h in hits}
        assert words == {"一站式"}
        assert stat.net_hits == 1 and stat.files == 1

    def test_md_surface_line_scan(self, sf, tmp_path):
        p = tmp_path / "page.md"
        p.write_text("干净的一行。\n海量小文件命中行。\n", encoding="utf-8")
        hits, stat = sf.scan_md_surface("docs_site", [p])
        assert [(h.line, h.word) for h in hits] == [(2, "海量")]
        assert stat.units == 2

    def test_i18n_values_scan_zh_and_en(self, sf):
        data = {
            "a.ok": {"zh": "一键搞定，轻松无忧", "en": "All done seamlessly."},
            "b.fact": {"zh": "锚注册表加载失败，可信度数字暂不可用",
                       "en": "Anchor registry failed to load."},
        }
        hits, stat = sf.scan_i18n_values(data)
        by_lang = {(h.key, h.cls) for h in hits}
        assert ("a.ok", "C1") in by_lang and ("a.ok", "C7") in by_lang
        assert ("b.fact", "C1") not in by_lang
        assert stat.units == 2 and stat.files == 1

    def test_run_scan_unknown_surface_rejected(self, sf):
        with pytest.raises(ValueError, match="未知扫描面"):
            sf.run_scan(["nope"])


# ─── 4. 白名单匹配语义 ─────────────────────────────────────────────────────

class TestWhitelistMatching:
    def test_path_only_entry_exempts_whole_file(self, sf, monkeypatch):
        monkeypatch.setattr(sf, "WHITELIST", (
            {"path": "docs/x.md", "reason": "词表定义页"},
        ))
        assert sf._check_whitelist("docs/x.md", 5, "赋能 anywhere") is not None
        assert sf._check_whitelist("docs/y.md", 5, "赋能 anywhere") is None

    def test_line_and_contains_scoped_entry(self, sf, monkeypatch):
        monkeypatch.setattr(sf, "WHITELIST", (
            {"path": "docs/x.md", "line": 7, "contains": "完美负载",
             "reason": "core docstring 逐字引文（RF 术语）"},
        ))
        assert sf._check_whitelist("docs/x.md", 7, "None=完美负载 地板") is not None
        assert sf._check_whitelist("docs/x.md", 8, "None=完美负载 地板") is None
        assert sf._check_whitelist("docs/x.md", 7, "完美用户") is None

    def test_hit_record_keeps_whitelisted_with_reason(self, sf, tmp_path, monkeypatch):
        # REPO_ROOT 指向 tmp：仓根相对路径语义与仓内面一致
        monkeypatch.setattr(sf, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sf, "WHITELIST", (
            {"path": "ui-copy-humanize.md", "reason": "守则词表页"},
        ))
        p = tmp_path / "ui-copy-humanize.md"
        p.write_text("词表行：赋能、抓手、一站式\n", encoding="utf-8")
        hits, _stat = sf.scan_md_surface("docs_site", [p])
        assert len(hits) == 3
        assert all(h.whitelisted and h.reason == "守则词表页" for h in hits)


# ─── 5. CLI 形态（--json / 退出码）─────────────────────────────────────────

class TestCli:
    def test_main_json_shape_and_exit_zero_on_clean_tree(self, sf, capsys):
        rc = sf.main(["--json"])
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert set(payload) == {"surfaces", "net_total", "hits"}
        assert set(payload["surfaces"]) == {
            "mcp_docstring", "envelope_msg", "report_narrative", "docs_site"}
        for s in payload["surfaces"].values():
            assert set(s) == {"files", "units", "raw_hits", "whitelisted", "net_hits"}
            assert s["files"] > 0
        assert payload["net_total"] == 0
        assert rc == 0

    def test_human_output_summary(self, sf, capsys):
        rc = sf.main([])
        out = capsys.readouterr().out
        assert "净命中合计 0" in out
        assert "mcp_docstring" in out and "envelope_msg" in out
        assert rc == 0


# ─── 6. 集成棘轮（当前树逐面净命中=0；i18n 面需 node，诚实门控）────────────

class TestLiveTreeRatchet:
    """四新面在当前树的词汇层零基线棘轮——新文案带套话入库即红（只收不放）。"""

    def test_mcp_docstring_surface_clean(self, sf):
        result = sf.run_scan(["mcp_docstring"])
        net = [h for h in result.hits if not h.whitelisted]
        assert net == [], f"MCP docstring 面净命中 {len(net)}: {[h.to_dict() for h in net]}"

    def test_envelope_msg_surface_clean(self, sf):
        result = sf.run_scan(["envelope_msg"])
        net = [h for h in result.hits if not h.whitelisted]
        assert net == [], f"信封文案面净命中 {len(net)}: {[h.to_dict() for h in net]}"

    def test_report_narrative_surface_clean(self, sf):
        result = sf.run_scan(["report_narrative"])
        net = [h for h in result.hits if not h.whitelisted]
        assert net == [], f"report narrative 面净命中 {len(net)}: {[h.to_dict() for h in net]}"

    def test_docs_site_surface_clean(self, sf):
        result = sf.run_scan(["docs_site"])
        net = [h for h in result.hits if not h.whitelisted]
        assert net == [], f"docs_site 面净命中 {len(net)}: {[h.to_dict() for h in net]}"
        # 白名单条目必须有命中在保（防白名单空转：条目删除/路径漂移即红）
        whitelisted_files = {h.file for h in result.hits if h.whitelisted}
        assert "docs_site/style/ui-copy-humanize.md" in whitelisted_files

    @pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用（i18n 新鲜 dump 需本地 import）")
    def test_i18n_fresh_dump_surface_clean(self, sf, tmp_path: Path):
        evidence = (REPO_ROOT / "runs" / "aurora_q" / "qw51_stats"
                    / "i18n_dump_fresh.json")
        if evidence.exists():
            data = json.loads(evidence.read_text(encoding="utf-8"))
        else:
            # 干净检出（证据区缺席）：按上文承诺现场重导（node 本地
            # import，零网络；等价 --i18n-dump 通道，dump_i18n_locales 单源）
            tmp_dump = tmp_path / "i18n_dump.json"
            sf.dump_i18n_locales(tmp_dump)
            data = json.loads(tmp_dump.read_text(encoding="utf-8"))
        # 优先用证据区新鲜 dump；缺失时现场重导（node 本地 import，零网络）
        result = sf.run_scan(["i18n"], i18n_data=data)
        net = [h for h in result.hits if not h.whitelisted]
        assert net == [], f"i18n 面净命中 {len(net)}: {[h.to_dict() for h in net]}"
        assert result.stats["i18n"].units > 1500  # 词表刷新面：≥1553 键口径（实测 1562）
