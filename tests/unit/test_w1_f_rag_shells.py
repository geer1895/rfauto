"""W1-F 席 D-08：rag hybrid/semantic CLI/MCP 薄壳回归钉。

X6 登记"rag hybrid/semantic CLI/MCP 薄壳"——服务面 semantic_query/hybrid_query
只收 RagIndex，本批补语料级一步式入口（semantic_query_corpus/hybrid_query_corpus）
并把 CLI ``rag query --mode`` 与 MCP ``rag_query`` 的 mode/alpha 参数接上。

纪律：全部离线零网络（缺省 embedder=确定性 hashing/TF-IDF 降级路线，
sentence-transformers 延迟 import 缺席=优雅降级，#105/#139）；词法缺省路径
零变化（mode 缺省 lexical → 原 query_corpus 直通）。
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rfauto.service.rag_service import (
    hybrid_query_corpus,
    query_corpus,
    semantic_query_corpus,
)


def _corpus(tmp_path: Path) -> Path:
    """离线小语料：docs/*.md + runs/<id>/meta.json（同 test_mcp_server 口径）。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text(
        "# Resonator Note\n\nresonator tuning stub design.\n", encoding="utf-8")
    runs = tmp_path / "runs"
    run_a = runs / "20261005_000000_ragw1f"
    run_a.mkdir(parents=True)
    (run_a / "meta.json").write_text(json.dumps({
        "run_id": run_a.name,
        "model": "wilkinson_power_divider",
        "adapter": "hfss",
        "status": "done",
    }), encoding="utf-8")
    return tmp_path


class TestSemanticHybridCorpusService:
    """服务面语料级语义/混合检索（JSON 信封，离线确定性）。"""

    def test_semantic_corpus_offline_degraded_route_declared(self, tmp_path):
        base = _corpus(tmp_path)
        result = semantic_query_corpus("resonator", docs_dir=str(base / "docs"),
                                       runs_dir=None, base_dir=str(base))
        assert result["ok"], result.get("errors")
        assert result["mode"] == "dense_semantic"
        assert result["semantic"] is False  # hashing/TF-IDF 降级路线如实声明
        assert result["n_hits"] >= 1
        assert any("降级" in note or "缺省" in note
                   for note in result.get("notes", []))
        hit = result["hits"][0]
        assert hit["citation"]["path"].endswith("note.md")

    def test_hybrid_corpus_alpha_zero_equals_lexical_order(self, tmp_path):
        """alpha=0（纯词法排序）命中序与纯 BM25 面一致（混合核融合语义对照）。"""
        base = _corpus(tmp_path)
        kw = dict(docs_dir=str(base / "docs"), runs_dir=str(base / "runs"),
                  base_dir=str(base))
        lexical = query_corpus("resonator", top_k=5, **kw)
        hybrid0 = hybrid_query_corpus("resonator", top_k=5, alpha=0.0, **kw)
        assert lexical["ok"] and hybrid0["ok"]
        assert hybrid0["mode"] == "hybrid_semantic"
        assert hybrid0["alpha"] == 0.0
        assert [h["chunk_id"] for h in hybrid0["hits"]] == \
            [h["chunk_id"] for h in lexical["hits"]]

    def test_hybrid_corpus_alpha_one_dense_side_only_order(self, tmp_path):
        """alpha=1（纯稠密排序）命中序与 semantic 面一致（另一侧锚点）。"""
        base = _corpus(tmp_path)
        kw = dict(docs_dir=str(base / "docs"), runs_dir=None, base_dir=str(base))
        semantic = semantic_query_corpus("resonator", top_k=5, **kw)
        hybrid1 = hybrid_query_corpus("resonator", top_k=5, alpha=1.0, **kw)
        assert semantic["ok"] and hybrid1["ok"]
        assert [h["chunk_id"] for h in hybrid1["hits"]] == \
            [h["chunk_id"] for h in semantic["hits"]]

    def test_missing_dir_returns_error_envelope_not_raise(self, tmp_path):
        result = semantic_query_corpus(
            "x", docs_dir=str(tmp_path / "nope"), runs_dir=None,
            base_dir=str(tmp_path))
        assert result["ok"] is False and result["errors"]


class TestRagQueryCliShell:
    """CLI ``rag query --mode`` 薄壳（词法缺省零变化 + 语义/混合三路）。"""

    def _invoke(self, tmp_path, *args: str):
        from rfauto.cli.domains.scattered import rag_app

        base = _corpus(tmp_path)
        runner = CliRunner()
        return runner.invoke(rag_app, [
            "query", "resonator",
            "--docs", str(base / "docs"), "--runs", str(base / "runs"),
            *args,
        ]), base

    def test_default_mode_lexical_unchanged(self, tmp_path):
        result, _ = self._invoke(tmp_path)
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc["ok"] and "mode" not in doc  # 词法面信封不带 mode 键（原样）

    def test_mode_semantic_offline(self, tmp_path):
        result, _ = self._invoke(tmp_path, "--mode", "semantic")
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc["ok"] and doc["mode"] == "dense_semantic"

    def test_mode_hybrid_with_alpha(self, tmp_path):
        result, _ = self._invoke(tmp_path, "--mode", "hybrid", "--alpha", "0.25")
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        assert doc["ok"] and doc["mode"] == "hybrid_semantic"
        assert doc["alpha"] == 0.25

    def test_mode_invalid_rejected(self, tmp_path):
        result, _ = self._invoke(tmp_path, "--mode", "bogus")
        assert result.exit_code != 0
        assert "lexical" in result.output
