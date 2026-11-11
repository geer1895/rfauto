"""T-Q19 批 1：厂商帮助文档 FTS5 检索层测试（Q-W6-4）。

全离线：语料=自造 mini HTML；PDF/CHM 通道=monkeypatch 钉（真机冒烟另走
runs/aurora_q/qw64_stats/smoke_chm.py）。覆盖：建表/插入去重/检索命中
排序/snippet/MATCH 语法错误处理/zero_ingest 审计/幂等重建/db_path None 拒写。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import vendor_doc_service as vds

DOC_EN = """<html><head><title>Wave Port Setup</title></head>
<body><h1>Wave Port</h1>
<p>Assign a wave port on the sheet body. The wave port excites the
mode on the port face. Wave port calibration deembedding removes the
feed length from the S-parameter reference plane.</p>
</body></html>"""

DOC_EN_DENSE = """<html><head><title>Capacitor Bank Notes</title></head>
<body><p>capacitor filler text one capacitor more filler two
capacitor more filler three tail text</p></body></html>"""

DOC_EN_SPARSE = """<html><head><title>Other Notes</title></head>
<body><p>capacitor single mention with a comparable amount of filler
text around it to keep document length similar</p></body></html>"""

DOC_CN = """<html><head><title>端口设置说明</title></head>
<body><p>波端口设置方法：先选中端口面，再赋激励。集总端口与波端口
的区别在于激励方式。 lumped port 与 wave port 对照。</p></body></html>"""

DOC_CN_BODY_ONLY = """<html><head><title> unrelated title </title></head>
<body><p>这里只讲集总端口，标题里没有端口两个字。</p></body></html>"""

CHM_INNER_1 = """<html><head><title>Ultracapacitor Model</title></head>
<body><p>The virtual gate array model supports ultracapacitor
characterization in Twin Builder.</p></body></html>"""

CHM_INNER_2 = """<html><head><title>Second Topic</title></head>
<body><p>Secondary page about gate arrays and modeling.</p></body></html>"""


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """手写 mini 语料：2 篇英文 + 2 篇中文 + 1 个未知后缀件。"""
    root = tmp_path / "corpus"
    _write(root, "guides/wave_port.html", DOC_EN)
    _write(root, "guides/capacitor.html", DOC_EN_DENSE)
    _write(root, "misc/other.html", DOC_EN_SPARSE)
    _write(root, "cn/ports.html", DOC_CN)
    _write(root, "cn/lumped.html", DOC_CN_BODY_ONLY)
    (root / "bin").mkdir()
    (root / "bin" / "asset.xyz").write_bytes(b"\x00\x01not a doc")
    return root


def _build(corpus: Path, db: Path, **kw) -> dict:
    kw.setdefault("chunk_chars", 1200)
    return vds.build_vendor_index({"ansys_help": corpus}, db_path=db, **kw)


# ---------------------------------------------------------------------------
# build：schema / 分块 / 限幅 / 跳过 / 容错
# ---------------------------------------------------------------------------


class TestBuild:
    def test_rejects_none_db_path(self, corpus):
        r = vds.build_vendor_index({"ansys_help": corpus}, db_path=None)
        assert not r["ok"]
        assert any("db_path" in e for e in r["errors"])

    def test_rejects_missing_root(self, tmp_path):
        r = vds.build_vendor_index(
            {"ansys_help": tmp_path / "nope"}, db_path=tmp_path / "x.db"
        )
        assert not r["ok"]
        assert any("nope" in e for e in r["errors"])

    def test_rejects_empty_roots(self, tmp_path):
        r = vds.build_vendor_index({}, db_path=tmp_path / "x.db")
        assert not r["ok"]

    def test_creates_schema_and_chunks(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"], r["errors"]
        assert r["indexed_files"] == 5
        assert r["skipped_files"] == 1  # asset.xyz
        assert r["total_chunks"] > 0
        conn = sqlite3.connect(str(db))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        assert {"vendor_docs", "vendor_files", "vendor_index_meta"} <= tables
        # fts 虚表
        conn = sqlite3.connect(str(db))
        fts = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='vendor_docs_fts'"
        ).fetchone()[0]
        conn.close()
        assert fts == 1

    def test_chunks_within_limit(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        r = _build(corpus, db, chunk_chars=60)
        assert r["ok"]
        conn = sqlite3.connect(str(db))
        mx = conn.execute(
            "SELECT MAX(LENGTH(chunk_text)) FROM vendor_docs"
        ).fetchone()[0]
        n = conn.execute("SELECT COUNT(*) FROM vendor_docs").fetchone()[0]
        conn.close()
        assert mx <= 60
        assert n > 5  # 60 字上限必然多块

    def test_html_strips_tags(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"]
        conn = sqlite3.connect(str(db))
        joined = " ".join(
            row[0]
            for row in conn.execute("SELECT chunk_text FROM vendor_docs")
        )
        conn.close()
        assert "<" not in joined and "html" not in joined.lower()
        assert "波端口设置方法" in joined
        assert "deembedding" in joined

    def test_max_docs_caps_files(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        r = _build(corpus, db, max_docs=2)
        assert r["ok"]
        assert r["indexed_files"] == 2

    def test_corrupt_file_best_effort(self, corpus, tmp_path, monkeypatch):
        def boom(path: Path) -> tuple[str, str]:
            raise vds.VendorDocError("HTML 解析失败: simulated")

        monkeypatch.setattr(vds, "_index_html_file", boom)
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"]  # 整批不中断
        assert len(r["errors"]) == 5  # 全部 HTML 件失败如实入账
        assert r["indexed_files"] == 0

    def test_pdf_unavailable_recorded(self, corpus, tmp_path, monkeypatch):
        # 语料加一个 .pdf 件、抽取通道模拟 ImportError 场景
        _write(corpus, "docs/manual.pdf", "%PDF-fake")
        monkeypatch.setattr(
            vds,
            "_extract_pdf_pages",
            lambda p, *, max_pages=None: (_ for _ in ()).throw(
                vds.VendorDocError("pypdf 不可用")
            ),
        )
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"]
        assert any("pypdf" in e for e in r["errors"])
        assert r["indexed_files"] == 5  # HTML 件照常入库


# ---------------------------------------------------------------------------
# 增量与幂等：sha256 去重 / rebuild
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_dedup_same_sha256(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        r1 = _build(corpus, db)
        assert r1["ok"] and r1["indexed_files"] == 5
        r2 = _build(corpus, db)
        assert r2["ok"]
        assert r2["dedup_skipped"] == 5
        assert r2["chunks_new"] == 0
        assert r2["total_chunks"] == r1["total_chunks"]

    def test_reindex_changed_file(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        r1 = _build(corpus, db)
        assert r1["ok"]
        target = corpus / "guides" / "wave_port.html"
        target.write_text(
            "<html><head><title>rewritten</title></head><body>"
            "brand new body content about radiation boundary</body></html>",
            encoding="utf-8",
        )
        r2 = _build(corpus, db)
        assert r2["ok"]
        assert r2["dedup_skipped"] == 4
        assert r2["indexed_files"] == 1
        conn = sqlite3.connect(str(db))
        n = conn.execute(
            "SELECT COUNT(*) FROM vendor_docs WHERE path=?",
            ("guides/wave_port.html",),
        ).fetchone()[0]
        stale = conn.execute(
            "SELECT COUNT(*) FROM vendor_docs WHERE chunk_text LIKE"
            " '%deembedding%'"
        ).fetchone()[0]
        conn.close()
        assert n == 1  # 新内容 1 块（无旧块残留重复）
        assert stale == 0  # 旧内容块已清

    def test_rebuild_full_recreates(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        _write(
            corpus,
            "new/added.html",
            "<html><body><p>freshly added topic about optimetrics</p>"
            "</body></html>",
        )
        r = _build(corpus, db, rebuild=True)
        assert r["ok"]
        assert r["indexed_files"] == 6  # 全量重建不受去重影响
        conn = sqlite3.connect(str(db))
        n_files = conn.execute("SELECT COUNT(*) FROM vendor_files").fetchone()[0]
        conn.close()
        assert n_files == 6
        # 检索面立即可见新件
        s = vds.search_vendor_docs("optimetrics", db_path=db)
        assert s["ok"] and s["total"] >= 1


# ---------------------------------------------------------------------------
# search：命中 / 排序 / snippet / 语法容错 / 回退
# ---------------------------------------------------------------------------


class TestSearch:
    def test_rejects_none_db_path(self):
        r = vds.search_vendor_docs("port", db_path=None)
        assert not r["ok"]

    def test_rejects_empty_query(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("   ", db_path=db)
        assert not r["ok"]

    def test_missing_db(self, tmp_path):
        r = vds.search_vendor_docs("port", db_path=tmp_path / "no.db")
        assert not r["ok"]
        assert any("不存在" in e for e in r["errors"])

    def test_unbuilt_db(self, tmp_path):
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()
        r = vds.search_vendor_docs("port", db_path=db)
        assert not r["ok"]
        assert any("未构建" in e for e in r["errors"])

    def test_english_hit_fields(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("deembedding", db_path=db)
        assert r["ok"] and r["total"] >= 1
        hit = r["hits"][0]
        assert {"source", "title", "path", "page", "snippet"} <= set(hit)
        assert hit["source"] == "ansys_help"
        assert hit["path"] == "guides/wave_port.html"
        assert hit["page"] is None  # HTML 无页码
        assert hit["title"] == "Wave Port Setup"
        assert hit["snippet"]  # snippet 非空

    def test_cjk_trigram_match(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("波端口", db_path=db)
        assert r["ok"] and r["total"] >= 1
        assert r["mode"] in ("fts5", "fts5_phrase")
        assert "[波端口]" in r["hits"][0]["snippet"]

    def test_cjk_short_like_fallback(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("端口", db_path=db)  # 2 字 < trigram 下限
        assert r["ok"]
        assert r["mode"] == "like"
        assert r["total"] >= 2  # 两篇中文件都含"端口"
        assert "[端口]" in r["hits"][0]["snippet"]

    def test_like_title_match_first(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("端口", db_path=db)
        # 标题含"端口"的件排在正文-only 件之前
        assert r["hits"][0]["title"] == "端口设置说明"

    def test_bm25_orders_by_term_frequency(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("capacitor", db_path=db)
        assert r["ok"] and r["total"] >= 2
        assert r["hits"][0]["path"] == "guides/capacitor.html"  # 3 次 > 1 次

    def test_match_syntax_error_no_raise(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        for bad in ('"', "AND AND (", "NEAR(", "^"):
            r = vds.search_vendor_docs(bad, db_path=db)  # 不得抛异常
            assert isinstance(r, dict) and "ok" in r

    def test_no_hits_total_zero(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("zzzqqq", db_path=db)
        assert r["ok"] and r["total"] == 0 and r["hits"] == []

    def test_limit_caps_hits(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        r = vds.search_vendor_docs("端口", db_path=db, limit=1)
        assert r["ok"] and len(r["hits"]) == 1
        assert r["limit"] == 1

    def test_multi_source_paths(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        _build(corpus, db)
        root2 = corpus.parent / "ads_doc"
        root2.mkdir()
        _write(
            root2,
            "sim/sweep.html",
            "<html><body><p>optimetric sweep configuration for the "
            "frequency sweep setup</p></body></html>",
        )
        r2 = vds.build_vendor_index(
            {"ads_doc": root2}, db_path=db
        )
        assert r2["ok"]
        r = vds.search_vendor_docs("optimetric", db_path=db)
        assert r["ok"] and r["total"] >= 1
        assert r["hits"][0]["source"] == "ads_doc"
        assert r["hits"][0]["path"] == "sim/sweep.html"


# ---------------------------------------------------------------------------
# PDF / CHM 通道（monkeypatch 钉；真机走 smoke_chm.py）
# ---------------------------------------------------------------------------


class TestPdfChannel:
    def _fake_extract(self, title: str, pages: list[tuple[int, str]]):
        return lambda p, *, max_pages=None: (title, pages)

    def test_pdf_pages_cited(self, corpus, tmp_path, monkeypatch):
        _write(corpus, "docs/hfss.pdf", "%PDF-fake")
        monkeypatch.setattr(
            vds,
            "_extract_pdf_pages",
            self._fake_extract(
                "HFSS User Guide",
                [(1, "mesh operations introduction"), (2, "boundary setup")],
            ),
        )
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"] and r["indexed_files"] == 6
        s1 = vds.search_vendor_docs("mesh operations", db_path=db)
        assert s1["ok"] and s1["total"] >= 1
        assert s1["hits"][0]["page"] == 1  # 引用指向原文页码
        s2 = vds.search_vendor_docs("boundary setup", db_path=db)
        assert s2["ok"] and s2["hits"][0]["page"] == 2

    def test_pdf_max_pages_limits(self, corpus, tmp_path, monkeypatch):
        _write(corpus, "docs/hfss.pdf", "%PDF-fake")
        seen: dict = {}

        def spy(path: Path, *, max_pages=None):
            seen["max_pages"] = max_pages
            n = 5 if max_pages is None else min(5, max_pages)
            return ("T", [(i + 1, f"page {i+1} text") for i in range(n)])

        monkeypatch.setattr(vds, "_extract_pdf_pages", spy)
        db = tmp_path / "idx.db"
        r = _build(corpus, db, pdf_max_pages=3)
        assert r["ok"]
        assert seen["max_pages"] == 3
        conn = sqlite3.connect(str(db))
        pages = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT page FROM vendor_docs WHERE path=?"
                " ORDER BY page",
                ("docs/hfss.pdf",),
            )
        ]
        conn.close()
        assert pages == [1, 2, 3]


class TestChmChannel:
    def _fake_decompile(self, files: dict[str, str], log: list):
        def fake(chm_path: Path, out_dir: Path, *, timeout_s: float = 60.0):
            log.append(str(chm_path))
            out_dir.mkdir(parents=True, exist_ok=True)
            for rel, text in files.items():
                p = out_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            return sorted(out_dir.rglob("*.htm*"))

        return fake

    def test_chm_inner_pages_cited(self, corpus, tmp_path, monkeypatch):
        _write(corpus, "chm/tb.chm", "MZ-fake-chm")
        log: list = []
        monkeypatch.setattr(
            vds,
            "_decompile_chm",
            self._fake_decompile(
                {"topic1.htm": CHM_INNER_1, "sub/topic2.htm": CHM_INNER_2},
                log,
            ),
        )
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"] and r["indexed_files"] == 6
        s = vds.search_vendor_docs("virtual gate array", db_path=db)
        assert s["ok"] and s["total"] >= 1
        hit = s["hits"][0]
        assert hit["path"] == "chm/tb.chm!topic1.htm"  # CHM 内页引用形态
        assert hit["page"] is None
        assert hit["title"] == "Ultracapacitor Model"

    def test_decompile_staging_whitespace_free(self, tmp_path, monkeypatch):
        """真 _decompile_chm 逻辑：staging 无空白+轮询+清理（#157 族纪律）。"""
        calls: list = []

        def fake_run(cmd, capture_output, timeout, check):
            calls.append(cmd)
            out_dir = Path(cmd[2])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.htm").write_text(
                "<html><body><p>decompiled content</p></body></html>",
                encoding="utf-8",
            )
            staged = Path(cmd[3])
            assert " " not in str(staged), f"staging 含空白: {staged}"
            assert " " not in str(out_dir), f"产物目录含空白: {out_dir}"
            from collections import namedtuple

            Ret = namedtuple("Ret", ["returncode", "stderr"])
            return Ret(0, b"")

        monkeypatch.setattr(vds.subprocess, "run", fake_run)
        monkeypatch.setattr(vds, "_find_hh_exe", lambda: "hh.exe")
        chm = tmp_path / "Twin Builder" / "lib chm.chm"  # 故意含空格
        chm.parent.mkdir(parents=True)
        chm.write_bytes(b"CHM")
        out = tmp_path / "chm_out"
        files = vds._decompile_chm(chm, out, timeout_s=10)
        assert len(files) == 1
        assert len(calls) == 1
        # 源 CHM 被拷贝到 staging（原路径不直接进 cmd）
        assert str(chm) not in calls[0]

    def test_decompile_timeout_zero_files(self, tmp_path, monkeypatch):
        def fake_run(cmd, capture_output, timeout, check):
            from collections import namedtuple

            Ret = namedtuple("Ret", ["returncode", "stderr"])
            return Ret(0, b"")  # rc=0 但零产物（hh.exe 静默失败形态）

        monkeypatch.setattr(vds.subprocess, "run", fake_run)
        monkeypatch.setattr(vds, "_find_hh_exe", lambda: "hh.exe")
        chm = tmp_path / "a.chm"
        chm.write_bytes(b"CHM")
        with pytest.raises(vds.VendorDocError, match="零产物"):
            vds._decompile_chm(chm, tmp_path / "out", timeout_s=1.0)

    def test_hh_unavailable_skips_file(self, corpus, tmp_path, monkeypatch):
        _write(corpus, "chm/tb.chm", "MZ-fake-chm")
        monkeypatch.setattr(vds, "_find_hh_exe", lambda: None)
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"]  # best-effort：CHM 失败不中断
        assert any("hh.exe" in e for e in r["errors"])
        assert r["indexed_files"] == 5


# ---------------------------------------------------------------------------
# zero_ingest_audit：零入库红线复核
# ---------------------------------------------------------------------------


class TestZeroIngestAudit:
    def test_rejects_none_and_missing(self, tmp_path):
        r0 = vds.zero_ingest_audit(db_path=None)
        assert not r0["ok"]
        r1 = vds.zero_ingest_audit(db_path=tmp_path / "no.db")
        assert not r1["ok"]

    def test_audit_fields(self, corpus, tmp_path):
        db = tmp_path / "idx.db"
        r = _build(corpus, db)
        assert r["ok"]
        a = vds.zero_ingest_audit(db_path=db)
        assert a["ok"]
        assert a["n_files"] == 5
        assert a["n_chunks"] == r["total_chunks"]
        assert a["by_source"]["ansys_help"]["files"] == 5
        assert a["sources"] == ["ansys_help"]
        assert a["within_chunk_limit"] is True
        assert a["max_chunk_chars"] <= 1200
        assert "零入仓" in a["note"]
        assert a["roots"]["ansys_help"] == str(corpus)

    def test_chunk_total_below_raw_bytes(self, corpus, tmp_path):
        """摘要块字符总量 < 语料原始字节（去标签+分块上界的可复核口径）。"""
        db = tmp_path / "idx.db"
        assert _build(corpus, db)["ok"]
        a = vds.zero_ingest_audit(db_path=db)
        raw = sum(
            p.stat().st_size
            for p in corpus.rglob("*")
            if p.is_file() and p.suffix in (".html",)
        )
        assert a["total_chunk_chars"] < raw


# ---------------------------------------------------------------------------
# rebuild 命令后 FTS 索引一致性（external content 同步）
# ---------------------------------------------------------------------------


def test_fts_sync_after_change(corpus, tmp_path):
    db = tmp_path / "idx.db"
    _build(corpus, db)
    target = corpus / "guides" / "wave_port.html"
    target.write_text(
        "<html><body><p>entirely fresh vocabulary xyzzy about ports</p>"
        "</body></html>",
        encoding="utf-8",
    )
    r2 = _build(corpus, db)
    assert r2["ok"]
    s = vds.search_vendor_docs("xyzzy", db_path=db)
    assert s["ok"] and s["total"] == 1  # 新词可检索（fts 已 rebuild）
    s_old = vds.search_vendor_docs("deembedding", db_path=db)
    assert s_old["total"] == 0  # 旧词不可再检索
