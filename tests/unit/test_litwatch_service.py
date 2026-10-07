"""KD-5 文献监控管线测试（round16 P2，J 流）。

锚树：
- **#139 网络通道钉死**：monkeypatch 模块级 _http_get 注入 canned Atom
  ——所有测试零真网；拔掉注入面直接真调=测试失败（防"配置存在则走
  外部服务"分支逃逸）；
- Atom 解析：id 规范化（去 abs/ 前缀与版本号保留）/空白折叠/作者表/
  无 id 条目跳过；
- 排序确定性：命中计降序→published 新文优先→id 字典序全序；
- 账本幂等：同 arxiv id 二次登记跳过（n_dup 计数）；坏行不中断；
- 候选状态恒 candidate（升格须人工双源核实，#300——本管线不升格）；
- 空查询/查询失败如实（ok=False / n_parse_error 计数不凑数）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

import rfauto.service.litwatch_service as lw
from rfauto.service.litwatch_service import (
    LITWATCH_SCHEMA,
    STATUS_CANDIDATE,
    build_query_url,
    parse_atom_feed,
    render_candidates_markdown,
    score_entry,
    watch,
)

_ENTRY_TPL = """<entry>
  <id>http://arxiv.org/abs/{eid}</id>
  <title>{title}</title>
  <summary>{summary}</summary>
  <published>{pub}</published>
  <updated>{pub}</updated>
  <author><name>{author}</name></author>
</entry>"""


def _feed(*entries: str) -> bytes:
    return (f"""<feed xmlns="http://www.w3.org/2005/Atom">
<title>arXiv Query</title>{''.join(entries)}</feed>""").encode()


class TestNetworkPinned:
    """#139：网络通道必须被钉住——注入缺失时不得真网。"""

    def test_http_get_is_module_level_single_point(self):
        # 全部 HTTP 收敛在 _http_get 单点（monkeypatch 目标稳定）
        assert callable(lw._http_get)

    def test_watch_without_injection_refuses_env_free_network(self, monkeypatch):
        # 拔网：把 _http_get 换成必炸哨兵——watch 内部必须走到它（说明
        # 没有绕过单点的旁路 HTTP），异常被记 parse_error 不静默成功
        def _boom(url, timeout):
            raise AssertionError(f"真网调用逃逸：{url}")

        monkeypatch.setattr(lw, "_http_get", _boom)
        r = watch(["antenna"], ledger_path=Path("unused.jsonl"))
        # 哨兵异常 → 每查询一次 parse_error，零条目零登记
        assert r["n_parse_error"] >= 1 and r["n_new"] == 0

    def test_fetch_fn_injection_is_zero_network(self, tmp_path):
        urls: list[str] = []

        def fake_fetch(url: str) -> bytes:
            urls.append(url)
            return _feed(_ENTRY_TPL.format(
                eid="2401.00001v1", title="Metasurface antenna",
                summary="A metasurface antenna study.", pub="2024-01-05",
                author="A. Researcher"))

        r = watch(["metasurface"], ledger_path=tmp_path / "c.jsonl",
                  fetch_fn=fake_fetch)
        assert r["ok"] and r["n_new"] == 1 and len(urls) == 1
        assert "export.arxiv.org" in urls[0]


class TestAtomParsing:
    def test_id_normalization_keeps_version(self):
        entries = parse_atom_feed(_feed(_ENTRY_TPL.format(
            eid="2411.13560v2", title="T", summary="S",
            pub="2024-11-20", author="X. Y")))
        assert entries[0]["arxiv_id"] == "2411.13560v2"
        assert entries[0]["url"].endswith("2411.13560v2")

    def test_whitespace_folded_and_authors(self):
        entries = parse_atom_feed(_feed(_ENTRY_TPL.format(
            eid="2401.00002", title="Line1\n  Line2", summary="S1\nS2",
            pub="2024-01-01", author="Ann B")))
        assert entries[0]["title"] == "Line1 Line2"
        assert entries[0]["summary"] == "S1 S2"
        assert entries[0]["authors"] == ["Ann B"]

    def test_entry_without_id_skipped(self):
        xml = (b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>no id</title></entry></feed>""")
        assert parse_atom_feed(xml) == []

    def test_malformed_xml_raises(self):
        from xml.etree import ElementTree
        with pytest.raises(ElementTree.ParseError):
            parse_atom_feed(b"<feed><entry>")


class TestRanking:
    def test_query_url_is_quoted_and_capped(self):
        url = build_query_url("pyramidal antenna", max_results=999)
        assert "max_results=100" in url and "export.arxiv.org" in url
        assert "pyramidal%20antenna" in url

    def test_score_counts_keyword_hits(self):
        e = {"title": "Additive manufactured horn", "summary": "3D printed antenna"}
        assert score_entry(e, ["additive", "horn", "absent"]) == 2
        assert score_entry(e, []) == 0

    def test_order_score_then_recency_then_id(self, tmp_path):
        def fake_fetch(url: str) -> bytes:
            return _feed(
                _ENTRY_TPL.format(eid="2401.00003", title="antenna old low",
                                  summary="antenna", pub="2023-01-01", author="A"),
                _ENTRY_TPL.format(eid="2401.00001", title="antenna new high score",
                                  summary="antenna pyramidal", pub="2024-06-01", author="A"),
                _ENTRY_TPL.format(eid="2401.00002", title="antenna old high",
                                  summary="antenna pyramidal", pub="2023-06-01", author="A"),
            )

        r = watch(["pyramidal"], ledger_path=tmp_path / "c.jsonl",
                  fetch_fn=fake_fetch)
        ids = [e["arxiv_id"] for e in r["entries"]]
        # 同分(1)的两条：新 published 优先；零分最后
        assert ids == ["2401.00001", "2401.00002", "2401.00003"]
        assert [e["score"] for e in r["entries"]] == [1, 1, 0]


class TestLedger:
    def test_idempotent_second_run_counts_dup(self, tmp_path):
        def fake_fetch(url: str) -> bytes:
            return _feed(_ENTRY_TPL.format(
                eid="2411.13560", title="KG circuit design", summary="graph RAG",
                pub="2024-11-20", author="X"))

        p = tmp_path / "candidates.jsonl"
        r1 = watch(["graph"], ledger_path=p, fetch_fn=fake_fetch)
        r2 = watch(["graph"], ledger_path=p, fetch_fn=fake_fetch)
        assert r1["n_new"] == 1 and r2["n_new"] == 0 and r2["n_dup"] == 1
        lines = [json.loads(ln) for ln in
                 p.read_text(encoding="utf-8").strip().splitlines()]
        assert len(lines) == 1

    def test_candidate_status_pinned_no_auto_promotion(self, tmp_path):
        def fake_fetch(url: str) -> bytes:
            return _feed(_ENTRY_TPL.format(
                eid="2401.00009", title="antenna", summary="antenna",
                pub="2024-01-01", author="A"))

        r = watch(["antenna"], ledger_path=tmp_path / "c.jsonl",
                  fetch_fn=fake_fetch)
        assert r["entries"][0]["status"] == STATUS_CANDIDATE
        assert "双源" in r["entries"][0]["verify_note"]

    def test_corrupt_ledger_lines_do_not_break(self, tmp_path):
        p = tmp_path / "c.jsonl"
        p.write_text("not-json\n{\"arxiv_id\": \"2401.00009\"}\n", encoding="utf-8")
        def fake_fetch(url: str) -> bytes:
            return _feed(_ENTRY_TPL.format(
                eid="2401.00009", title="dup", summary="dup",
                pub="2024-01-01", author="A"))
        r = watch(["antenna"], ledger_path=p, fetch_fn=fake_fetch)
        assert r["n_new"] == 0 and r["n_dup"] == 1  # 好行仍被识别

    def test_empty_queries_rejected(self, tmp_path):
        r = watch([], ledger_path=tmp_path / "c.jsonl", fetch_fn=lambda u: b"")
        assert not r["ok"]

    def test_schema_pinned_and_deterministic_record(self, tmp_path):
        def fake_fetch(url: str) -> bytes:
            return _feed(_ENTRY_TPL.format(
                eid="2401.00010", title="t", summary="s",
                pub="2024-01-01", author="A"))

        r = watch(["t"], ledger_path=tmp_path / "c.jsonl",
                  fetch_fn=fake_fetch, now=__import__("datetime").datetime(
                      2026, 10, 3, tzinfo=__import__("datetime").timezone.utc))
        assert r["schema"] == LITWATCH_SCHEMA
        rec = r["entries"][0]
        assert rec["registered_at"] == "2026-10-03T00:00:00+00:00"
        # sort_keys 往返逐位一致（确定性契约）
        assert json.dumps(rec, sort_keys=True, ensure_ascii=False) == \
            json.dumps(json.loads(json.dumps(rec)), sort_keys=True,
                       ensure_ascii=False)

    def test_min_score_filter(self, tmp_path):
        def fake_fetch(url: str) -> bytes:
            return _feed(
                _ENTRY_TPL.format(eid="2401.00011", title="unrelated",
                                  summary="nothing", pub="2024-01-01", author="A"),
                _ENTRY_TPL.format(eid="2401.00012", title="filter antenna",
                                  summary="filter", pub="2024-01-02", author="A"))

        r = watch(["antenna"], ledger_path=tmp_path / "c.jsonl",
                  fetch_fn=fake_fetch, min_score=1)
        assert [e["arxiv_id"] for e in r["entries"]] == ["2401.00012"]


class TestRender:
    def test_markdown_lists_candidates(self, tmp_path):
        def fake_fetch(url: str) -> bytes:
            return _feed(_ENTRY_TPL.format(
                eid="2401.00013", title="Horn antenna", summary="horn",
                pub="2024-01-01", author="A"))

        r = watch(["horn"], ledger_path=tmp_path / "c.jsonl",
                  fetch_fn=fake_fetch)
        md = render_candidates_markdown(r)
        assert "candidate" in md and "2401.00013" in md and "双源" in md

    def test_empty_result_renders_empty(self):
        assert render_candidates_markdown({"ok": True, "entries": []}) == ""
        assert render_candidates_markdown({"ok": False}) == ""
