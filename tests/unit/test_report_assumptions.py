"""XN-5 报告假设论证模式测试（ge8c 席C6）。

锚定：
- UNVERIFIED docstring 抽取：模块/类/函数三层 docstring 命中+行号可溯；
  无标签如实空；语法坏文件 skipped 不炸批次；缺路径 skipped；
- 判据 domain 盾：已声明→边界陈述；缺 domain→「未声明」如实条目；
- bounds 裁决：unreachable/marginal→反例；undefined→如实未判；
- 三段齐备性 + 确定性 + Markdown 三标题完整性（#146 家族锚）。
"""

from __future__ import annotations

import json

from rfauto.service.report_assumptions import (
    ASSUMPTIONS_SCHEMA,
    collect_unverified_from_sources,
    render_assumptions_markdown,
    report_assumptions,
)

_SRC_WITH_TAGS = '''\
"""模块 docstring。

UNVERIFIED: 本模块常数 k 的文献出处待二次核对。
"""


class Foo:
    """类说明。

    UNVERIFIED: 边界带外行为未验证。
    """

    def bar(self):
        """函数 doc。

        some line
        UNVERIFIED: 端到端口径未验证。
        """
        return 0
'''

_SRC_CLEAN = '"""干净模块，无标签。"""\n\n\ndef f():\n    return 1\n'


class TestUnverifiedExtraction:
    def test_extract_three_levels_with_lines(self, tmp_path) -> None:
        p = tmp_path / "tagged.py"
        p.write_text(_SRC_WITH_TAGS, encoding="utf-8")
        hits, skipped = collect_unverified_from_sources([str(p)])
        assert skipped == []
        assert len(hits) == 3
        assert all(h["text"].startswith("UNVERIFIED") for h in hits)
        # 行号随 docstring 节点定位（>= 各 docstring 起始行）
        assert hits[0]["line"] >= 1

    def test_clean_source_empty_honest(self, tmp_path) -> None:
        p = tmp_path / "clean.py"
        p.write_text(_SRC_CLEAN, encoding="utf-8")
        hits, skipped = collect_unverified_from_sources([str(p)])
        assert hits == [] and skipped == []

    def test_missing_and_broken_sources_skipped(self, tmp_path) -> None:
        bad = tmp_path / "broken.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        hits, skipped = collect_unverified_from_sources(
            [str(tmp_path / "nope.py"), str(bad)])
        assert hits == []
        assert len(skipped) == 2
        assert {s["source"] for s in skipped} == {
            str(tmp_path / "nope.py"), str(bad)}

    def test_unknown_module_skipped(self) -> None:
        hits, skipped = collect_unverified_from_sources(
            ["no_such_module_xyz_42"])
        assert hits == [] and len(skipped) == 1

    def test_real_repo_module_scannable(self) -> None:
        # 仓内真实模块（本席 emp_hemp docstring 无 UNVERIFIED 词——空也算过）
        hits, skipped = collect_unverified_from_sources(
            ["rfauto.core.emp_hemp"])
        assert skipped == []
        assert isinstance(hits, list)


class TestThreeSections:
    def test_full_report(self) -> None:
        r = report_assumptions(
            criteria_domains=[
                {"id": "patch_eta_window", "domain": "patch"},
                {"id": "no_domain_gate"},
            ],
            bounds_verdicts=[
                {"id": "chu_q", "verdict": "unreachable"},
                {"id": "bode_fano", "verdict": "marginal"},
                {"id": "no_target", "verdict": "undefined"},
                {"id": "fine", "verdict": "reachable"},
            ],
            sources=["rfauto.core.emp_hemp"],
        )
        assert r["ok"] is True
        assert r["schema"] == ASSUMPTIONS_SCHEMA
        sec = r["sections"]
        assert len(sec["boundary"]) == 2
        by_id = {b["criteria_id"]: b for b in sec["boundary"]}
        assert "仅适用于域" in by_id["patch_eta_window"]["statement"]
        assert by_id["no_domain_gate"]["declared"] is False
        assert "未声明" in by_id["no_domain_gate"]["statement"]
        assert len(sec["counterexamples"]) == 3  # undefined 如实入账
        und = [c for c in sec["counterexamples"] if c["verdict"] == "undefined"]
        assert "不构成反例" in und[0]["statement"]
        assert "reachable" not in {
            c["verdict"] for c in sec["counterexamples"]}

    def test_empty_inputs_all_empty(self) -> None:
        r = report_assumptions()
        assert r["ok"] is True
        assert all(len(v) == 0 for v in r["sections"].values())
        assert r["n_items"] == 0

    def test_deterministic(self, tmp_path) -> None:
        p = tmp_path / "tagged.py"
        p.write_text(_SRC_WITH_TAGS, encoding="utf-8")
        kw = {"criteria_domains": [{"id": "g", "domain": "d"}],
              "bounds_verdicts": [{"id": "b", "verdict": "marginal"}],
              "sources": [str(p)]}
        a = json.dumps(report_assumptions(**kw), sort_keys=True)
        b = json.dumps(report_assumptions(**kw), sort_keys=True)
        assert a == b


class TestMarkdown:
    def test_titles_complete(self, tmp_path) -> None:
        p = tmp_path / "tagged.py"
        p.write_text(_SRC_WITH_TAGS, encoding="utf-8")
        r = report_assumptions(
            criteria_domains=[{"id": "g1", "domain": "patch"}],
            bounds_verdicts=[{"id": "b1", "verdict": "unreachable"}],
            sources=[str(p)])
        md = render_assumptions_markdown(r)
        for head in ("一、适用边界", "二、潜在反例", "三、未验证假设"):
            assert head in md  # #146 家族：三标题必须齐全
        assert "UNVERIFIED" in md
        assert f"{p.name}:" in md

    def test_empty_report_honest_wording(self) -> None:
        md = render_assumptions_markdown(report_assumptions())
        assert "非「全域适用」" in md
        assert "非「已验证」" in md

    def test_failure_honest(self) -> None:
        md = render_assumptions_markdown({"ok": False, "errors": ["x"]})
        assert "失败" in md
