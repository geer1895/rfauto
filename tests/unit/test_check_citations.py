"""check_citations.py 的纯函数回归钉（Z-2）。

在线面 probe_url 由 monkeypatch 桩住（#139：单测禁网络）；
提取/去重/报告/退出码语义全部离线验证。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.check_citations import (
    Citation,
    Report,
    check_online,
    collect_citations,
    dedupe,
    extract_urls_from_text,
    main,
    probe_url,
    write_report,
)


class TestExtract:
    def test_line_numbers_and_trailing_punct(self) -> None:
        text = "见 https://example.com/a，以及\n第二行 https://example.com/b)."
        hits = extract_urls_from_text(text)
        assert hits == [(1, "https://example.com/a"), (2, "https://example.com/b")]

    def test_no_url_empty(self) -> None:
        assert extract_urls_from_text("内部指针 runs/df5 与 。") == []

    def test_中文右括号不吞(self) -> None:
        hits = extract_urls_from_text("[源](https://example.com/c）尾注")
        assert hits[0][1] == "https://example.com/c"


class TestCollectDedupe:
    def test_collect_skips_bad_file_and_excludes_handoff(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "knowledge" / "ok.yaml").write_text(
            "ref: https://example.com/k1\n", encoding="utf-8"
        )
        (tmp_path / "knowledge" / "bad.yaml").write_bytes(b"\xff\xfe\x00bad")
        (tmp_path / "docs" / "handoff_x.md").write_text(
            "https://example.com/skip\n", encoding="utf-8"
        )
        (tmp_path / "docs" / "user.md").write_text(
            "a https://example.com/d1\nb https://example.com/d1\n", encoding="utf-8"
        )
        cits, skipped = collect_citations(["knowledge/*.yaml", "docs/*.md"], root=tmp_path)
        assert skipped == 1  # bad.yaml 跳过如实计数
        urls = {c.url for c in cits}
        assert urls == {"https://example.com/k1", "https://example.com/d1"}
        assert all(not c.file.startswith("docs/任务书") for c in cits)
        by_url = dedupe(cits)
        assert len(by_url["https://example.com/d1"]) == 2  # 同 URL 两处出现面


class TestCheckOnline:
    def test_dead_error_classification_and_occurrences(self, monkeypatch: pytest.MonkeyPatch) -> None:
        by_url = {
            "https://example.com/ok": [Citation("https://example.com/ok", "docs/a.md", 1)],
            "https://example.com/dead": [
                Citation("https://example.com/dead", "docs/a.md", 3),
                Citation("https://example.com/dead", "knowledge/b.yaml", 7),
            ],
            "https://example.com/neterr": [
                Citation("https://example.com/neterr", "docs/c.md", 2)
            ],
        }

        def fake_probe(url: str, timeout_s: float = 10.0) -> tuple[str, str]:
            table = {
                "https://example.com/ok": ("200", "HEAD ok"),
                "https://example.com/dead": ("404", "HEAD HTTP 404"),
                "https://example.com/neterr": ("error", "URLError: x"),
            }
            return table[url]

        monkeypatch.setattr("scripts.check_citations.probe_url", fake_probe)
        rep = check_online(by_url)
        assert isinstance(rep, Report)
        assert rep.n_unique == 3
        assert [e["url"] for e in rep.dead] == ["https://example.com/dead"]
        assert rep.dead[0]["occurrences"] == [
            {"file": "docs/a.md", "line": 3},
            {"file": "knowledge/b.yaml", "line": 7},
        ]
        assert [e["url"] for e in rep.errors] == ["https://example.com/neterr"]

    def test_3xx_counts_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.check_citations.probe_url", lambda url, timeout_s=10.0: ("301", "HEAD ok")
        )
        rep = check_online({"https://example.com/moved": [Citation("https://example.com/moved", "a", 1)]})
        assert rep.dead == [] and rep.errors == []


class TestMainOffline:
    def test_offline_list_mode_rc0_and_report(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "knowledge").mkdir()
        (tmp_path / "knowledge" / "refs.yaml").write_text(
            "u: https://example.com/x\n", encoding="utf-8"
        )
        out = tmp_path / "report.md"
        rc = main(["--root", str(tmp_path), "--source", "knowledge/*.yaml", "--out", str(out)])
        assert rc == 0
        text = out.read_text(encoding="utf-8")
        assert "未开启" in text and "1" in text
        assert "citations=1" in capsys.readouterr().out

    def test_check_mode_dead_rc1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "knowledge").mkdir()
        (tmp_path / "knowledge" / "refs.yaml").write_text(
            "u: https://example.com/gone\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            "scripts.check_citations.probe_url", lambda url, timeout_s=10.0: ("410", "HEAD HTTP 410")
        )
        out = tmp_path / "report.md"
        rc = main(["--root", str(tmp_path), "--source", "knowledge/*.yaml", "--out", str(out), "--check"])
        assert rc == 1
        assert "[410] https://example.com/gone" in out.read_text(encoding="utf-8")


class TestWriteReport:
    def test_report_contains_dead_section(self, tmp_path: Path) -> None:
        rep = Report(n_unique=2, dead=[{"url": "u", "status": "404", "detail": "d",
                                   "occurrences": [{"file": "docs/x.md", "line": 9}]}])
        out = tmp_path / "r.md"
        write_report(out, [Citation("u", "docs/x.md", 9)], 0, rep)
        text = out.read_text(encoding="utf-8")
        assert "dead（4xx/5xx）1" in text and "docs/x.md:9" in text


def test_probe_url_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """网络不可达环境（本仓 CI）下 probe_url 返回 error 形态不抛异常。"""

    def boom(req, timeout=0):  # type: ignore[no-untyped-def]
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    status, detail = probe_url("https://example.invalid/x")
    assert status == "error"
    assert "OSError" in detail
