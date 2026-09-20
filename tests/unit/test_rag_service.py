"""F2 RAG 知识库定向测试（确定性、零网络；tmp_path 小语料，不依赖真实 docs/runs）。

覆盖：分词/切块确定性、BM25 已知排序、citation 可溯（路径真实存在）、top_k
边界、空查询/空库/未知词显式行为、逐字节确定性、非法输入、embedder 可插拔占位。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.rag_service import (
    RagIndex,
    build_index,
    explain,
    explain_corpus,
    index_corpus,
    query,
    query_corpus,
    split_markdown,
    tokenize,
)

DOC_FREQ = (
    "# Frequency Note\n"
    "\n"
    "resonator resonator resonator resonator resonator tuning.\n"
)

DOC_ONCE = (
    "# Once Note\n"
    "\n"
    "resonator appears once here but this document is longer with filler\n"
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu.\n"
)

DOC_CJK = (
    "# 中文微带\n"
    "\n"
    "微带线阻抗匹配 stub 设计。\n"
)

DOC_TRACE = (
    "# Trace Target\n"
    "\n"
    "preamble line.\n"
    "\n"
    "## Secret Section\n"
    "\n"
    "zebra unicorn\n"
)


@pytest.fixture
def docs_dir(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "freq.md").write_text(DOC_FREQ, encoding="utf-8")
    (docs / "once.md").write_text(DOC_ONCE, encoding="utf-8")
    (docs / "cjk.md").write_text(DOC_CJK, encoding="utf-8")
    (docs / "trace.md").write_text(DOC_TRACE, encoding="utf-8")
    return docs


@pytest.fixture
def index(tmp_path, docs_dir):
    return build_index(docs_dir=docs_dir, base_dir=tmp_path)


class _FakeEmbedder:
    """仅满足 Embedder 协议的哑实现（本项不实现向量检索）。"""

    def embed(self, texts):
        return [[0.0] for _ in texts]


# ---------------------------------------------------------------------------
# 分词 / 切块
# ---------------------------------------------------------------------------

def test_tokenize_ascii_and_cjk_deterministic():
    assert tokenize("Resonator RESONATOR") == ["resonator", "resonator"]
    assert tokenize("微带线") == ["微带", "带线"]
    assert tokenize("单") == ["单"]
    assert tokenize("") == []
    assert tokenize("!!! ---") == []


def test_tokenize_rejects_non_string():
    with pytest.raises(ValueError):
        tokenize(None)


def test_split_markdown_tracks_heading_and_line():
    parts = split_markdown(DOC_TRACE)
    assert [(p["heading"], p["line"]) for p in parts] == [
        ("Trace Target", 1),
        ("Secret Section", 5),
    ]
    assert parts[1]["text"].startswith("Secret Section")
    assert "zebra unicorn" in parts[1]["text"]


def test_split_markdown_hard_splits_long_section():
    parts = split_markdown("# H\n\n" + "x" * 25, max_chars=10)
    assert len(parts) > 1
    assert all(len(p["text"]) <= 10 for p in parts)
    assert all(p["line"] == 1 for p in parts)


def test_split_markdown_rejects_bad_max_chars():
    with pytest.raises(ValueError):
        split_markdown("# H\n\nbody", max_chars=0)


# ---------------------------------------------------------------------------
# citation 可溯
# ---------------------------------------------------------------------------

def test_query_hit_citation_is_traceable(index, tmp_path):
    result = index.query("zebra", top_k=3)
    assert result["ok"] is True
    assert result["n_hits"] == 1
    citation = result["hits"][0]["citation"]
    assert citation["kind"] == "doc"
    assert citation["path"] == "docs/trace.md"
    assert citation["heading"] == "Secret Section"
    assert citation["line"] == 5
    resolved = index.resolve(citation)
    assert resolved == tmp_path / "docs" / "trace.md"
    assert resolved.is_file()


def test_query_hits_known_chunk_with_snippet(index):
    result = index.query("unicorn")
    assert result["hits"][0]["citation"]["heading"] == "Secret Section"
    assert "unicorn" in result["hits"][0]["snippet"]


# ---------------------------------------------------------------------------
# BM25 打分
# ---------------------------------------------------------------------------

def test_bm25_ranks_high_frequency_doc_first(index):
    result = index.query("resonator", top_k=5)
    paths = [hit["citation"]["path"] for hit in result["hits"]]
    assert paths[0] == "docs/freq.md"
    assert paths[1] == "docs/once.md"
    scores = [hit["score"] for hit in result["hits"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > scores[1]


def test_explain_exposes_bm25_score_breakdown(index):
    result = index.explain("resonator", top_k=2)
    hit = result["hits"][0]
    breakdown = hit["score_breakdown"]
    assert [item["term"] for item in breakdown] == ["resonator"]
    assert breakdown[0]["tf"] == 5
    assert breakdown[0]["df"] == 2
    assert breakdown[0]["idf"] > 0.0
    assert breakdown[0]["contribution"] == pytest.approx(hit["score"])


# ---------------------------------------------------------------------------
# top_k 边界
# ---------------------------------------------------------------------------

def test_query_top_k_one_limits_hits(index):
    result = index.query("resonator", top_k=1)
    assert result["n_hits"] == 1
    assert result["n_matched"] == 2


def test_query_top_k_larger_than_corpus_returns_all_matches(index):
    result = index.query("resonator", top_k=999)
    assert result["n_hits"] == 2


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "3", None])
def test_query_rejects_invalid_top_k(index, bad):
    with pytest.raises(ValueError):
        index.query("resonator", top_k=bad)


# ---------------------------------------------------------------------------
# 空查询 / 空库 / 未知词 / 非法输入
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("empty", ["", "   ", "\n\t", "!!! ---"])
def test_empty_query_is_explicit_not_hit(index, empty):
    result = index.query(empty)
    assert result["ok"] is False
    assert result["errors"]
    assert result["n_hits"] == 0
    assert result["hits"] == []


@pytest.mark.parametrize("bad", [None, 123, ["resonator"]])
def test_query_rejects_non_string_text(index, bad):
    with pytest.raises(ValueError):
        index.query(bad)


def test_empty_index_is_explicit():
    result = RagIndex().query("resonator")
    assert result["ok"] is True
    assert result["n_indexed"] == 0
    assert result["hits"] == []
    assert result["notes"] == ["索引为空"]


def test_unknown_term_returns_empty_hits(index):
    result = index.query("nonexistentterm")
    assert result["ok"] is True
    assert result["n_matched"] == 0
    assert result["hits"] == []


# ---------------------------------------------------------------------------
# 逐字节确定性
# ---------------------------------------------------------------------------

def test_query_is_byte_identical_across_calls(index):
    first = json.dumps(index.query("resonator", top_k=3),
                       ensure_ascii=False, sort_keys=True)
    second = json.dumps(index.query("resonator", top_k=3),
                        ensure_ascii=False, sort_keys=True)
    assert first == second


def test_rebuilt_index_dumps_byte_identical(index, docs_dir, tmp_path):
    rebuilt = build_index(docs_dir=docs_dir, base_dir=tmp_path)
    assert index.dumps() == rebuilt.dumps()


# ---------------------------------------------------------------------------
# CJK 检索与统计
# ---------------------------------------------------------------------------

def test_cjk_query_hits_cjk_chunk(index):
    result = index.query("阻抗")
    assert result["n_hits"] == 1
    assert result["hits"][0]["citation"]["path"] == "docs/cjk.md"


def test_stats_reports_chunk_and_vocab_counts(index):
    stats = index.stats()
    assert stats["ok"] is True
    assert stats["n_chunks"] == 5
    assert stats["source_kinds"] == {"doc": 5}
    assert stats["vocab_size"] > 0
    assert stats["embedder_configured"] is False


# ---------------------------------------------------------------------------
# runs/ 元数据
# ---------------------------------------------------------------------------

def test_index_runs_builds_traceable_entries(tmp_path):
    runs = tmp_path / "runs"
    run_a = runs / "20260101_000000_aaaaaaaa"
    run_a.mkdir(parents=True)
    (run_a / "meta.json").write_text(json.dumps({
        "run_id": run_a.name,
        "model": "wilkinson_power_divider",
        "adapter": "hfss",
        "status": "done",
        "study_name": "tune_wilkinson_pd_v1",
        "seed": 7,
        "metrics": {"s11_db_max_in_band": -18.2},
    }), encoding="utf-8")
    (run_a / "recipe.snapshot.yaml").write_text(
        "model: wilkinson_power_divider\n"
        "params:\n"
        "  arm_len_mm:\n"
        "    value: 20.5\n"
        "  series_w_mm:\n"
        "    value: 0.33\n"
        "optimization:\n"
        "  params:\n"
        "    arm_len_mm:\n"
        "      low: 18.0\n"
        "      high: 23.0\n",
        encoding="utf-8")

    index = RagIndex(base_dir=tmp_path)
    assert index.index_runs(runs) == 2

    result = index.query("hfss wilkinson", top_k=5)
    paths = {hit["citation"]["path"] for hit in result["hits"]}
    assert "runs/20260101_000000_aaaaaaaa/meta.json" in paths
    meta_hit = next(hit for hit in result["hits"]
                    if hit["citation"]["field"] == "meta.json")
    assert meta_hit["citation"]["run_id"] == run_a.name
    assert index.resolve(meta_hit["citation"]).is_file()

    param = index.query("series_w_mm")
    assert param["n_hits"] >= 1
    assert param["hits"][0]["citation"]["field"] == "recipe.snapshot.yaml"
    assert index.resolve(param["hits"][0]["citation"]).is_file()


def test_index_runs_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        RagIndex(base_dir=tmp_path).index_runs(tmp_path / "nope")


def test_index_documents_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        RagIndex(base_dir=tmp_path).index_documents(tmp_path / "nope")


# ---------------------------------------------------------------------------
# 入库校验 / embedder 占位 / 服务层函数
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [{}, {"path": ""}, {"path": 3}, None, "notadict"])
def test_add_chunk_rejects_invalid_citation(bad):
    with pytest.raises(ValueError):
        RagIndex().add_chunk("hello world", bad)


@pytest.mark.parametrize("bad", ["", "   ", None, 5])
def test_add_chunk_rejects_empty_text(bad):
    with pytest.raises(ValueError):
        RagIndex().add_chunk(bad, {"path": "docs/x.md"})


def test_embedder_hook_reserved_but_vector_query_unimplemented():
    index = RagIndex(embedder=_FakeEmbedder())
    index.add_chunk("resonator tuning", {"path": "docs/x.md"})
    assert index.stats()["embedder_configured"] is True
    assert index.query("resonator")["n_hits"] == 1
    with pytest.raises(NotImplementedError):
        index.vector_query("resonator")


def test_service_level_query_and_explain_wrap_index(index):
    result = query(index, "resonator", 1)
    assert result["n_hits"] == 1
    explained = explain(index, "resonator", 1)
    assert "score_breakdown" in explained["hits"][0]
    with pytest.raises(ValueError):
        query("not-an-index", "resonator")


def test_bm25_hyperparameters_validated():
    with pytest.raises(ValueError):
        RagIndex(k1=-1.0)
    with pytest.raises(ValueError):
        RagIndex(b=1.5)


# ---------------------------------------------------------------------------
# 一步式语料包装（CLI/MCP 薄壳消费的 JSON 信封）
# ---------------------------------------------------------------------------

def test_index_corpus_returns_stats_envelope(docs_dir, tmp_path):
    stats = index_corpus(docs_dir=docs_dir, base_dir=tmp_path)
    assert stats["ok"] is True
    assert stats["n_chunks"] == 5
    assert stats["source_kinds"] == {"doc": 5}


def test_query_corpus_matches_prebuilt_index(index, docs_dir, tmp_path):
    direct = index.query("resonator", top_k=2)
    wrapped = query_corpus("resonator", top_k=2, docs_dir=docs_dir, base_dir=tmp_path)
    assert json.dumps(wrapped, sort_keys=True) == json.dumps(direct, sort_keys=True)
    assert (tmp_path / wrapped["hits"][0]["citation"]["path"]).is_file()


def test_explain_corpus_carries_breakdown(docs_dir, tmp_path):
    explained = explain_corpus("resonator", top_k=1, docs_dir=docs_dir, base_dir=tmp_path)
    assert explained["ok"] is True
    assert explained["hits"][0]["score_breakdown"][0]["term"] == "resonator"


def test_corpus_wrappers_envelope_missing_dir_instead_of_raising(tmp_path):
    for fn in (
        lambda: index_corpus(docs_dir=tmp_path / "nope", base_dir=tmp_path),
        lambda: query_corpus("resonator", docs_dir=tmp_path / "nope", base_dir=tmp_path),
        lambda: explain_corpus("resonator", runs_dir=tmp_path / "nope", base_dir=tmp_path),
    ):
        result = fn()
        assert result["ok"] is False
        assert result["errors"] and "索引构建失败" in result["errors"][0]


def test_corpus_wrappers_none_dirs_yield_explicit_empty_index():
    result = query_corpus("resonator")
    assert result["ok"] is True
    assert result["n_indexed"] == 0
    assert result["hits"] == []
