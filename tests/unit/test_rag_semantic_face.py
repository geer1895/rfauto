"""KD-2 语义消费面回归钉（ge8e X6 批；rag_service 新增语义档 v1）。

锚点面：
- 语料注入→检索召回钉：合成语料查已知条目 rank1 命中（semantic_query /
  query_with_embedder / hybrid_query 三入口）；
- 降级钉：sentence-transformers 缺席（sys.modules 钉 None）→ 优雅回退缺省
  hashing/TF-IDF（#105），在场（stub 模块）→ 延迟换装生效；
- 坏向量拒收钉：外部 embedder 输出长度/维度/元素/有限性畸形 → ValueError，
  绝不静默消费；
- 零破坏钉：RagIndex.vector_query 占位契约（NotImplementedError）与 BM25
  query() 信封键集原样（既有 tests/unit/test_rag_service.py 不改写的隔离
  证明）；
- 确定性钉：三入口两次调用 JSON 逐字节一致。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.rag_embedding import HashEmbedder
from rfauto.service.rag_service import (
    SEMANTIC_FACE_VERSION,
    RagIndex,
    hybrid_query,
    query_with_embedder,
    resolve_embedder,
    semantic_query,
)

# ---------------------------------------------------------------------------
# 固定语料（词面可分的 4 条合成块）
# ---------------------------------------------------------------------------

_CORPUS: list[tuple[str, str]] = [
    ("wk", "wilkinson 功分器 隔离电阻 等分 S11 回损 isolation"),
    ("siw", "SIW 基片集成波导 金属化过孔 截止频率 via fence"),
    ("sob", "Sobol 灵敏度 Saltelli 采样 全局敏感性 指数"),
    ("pcb", "KiCad pcbnew ZONE 铜皮 填充 DRC footprint"),
]


def _build_index() -> RagIndex:
    index = RagIndex()
    for cid, text in _CORPUS:
        index.add_chunk(text, {"path": f"corpus/{cid}.md"}, chunk_id=cid)
    return index


class _FakeEmbedder:
    """协议同形的最小 embedder（恒等向量：可预测的稠密排序）。"""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim

    def embed(self, texts):
        return [[float(len(t) % self.dim), 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                for t in texts]


# ---------------------------------------------------------------------------
# resolve_embedder：降级钉 + 换装钉
# ---------------------------------------------------------------------------

class TestResolveEmbedder:
    def test_hashing_direct(self) -> None:
        result = resolve_embedder("hashing")
        assert result["source"] == "hashing_tfidf"
        assert result["semantic"] is False
        assert isinstance(result["embedder"], HashEmbedder)

    def test_auto_without_model_uses_default(self) -> None:
        result = resolve_embedder("auto")
        assert result["source"] == "hashing_tfidf"
        assert result["semantic"] is False
        assert any("缺省" in note for note in result["notes"])

    def test_auto_falls_back_when_st_absent(self) -> None:
        monkey_none = {**sys.modules, "sentence_transformers": None}
        orig = sys.modules
        sys.modules = monkey_none  # type: ignore[assignment]
        try:
            result = resolve_embedder("auto", model="fake/bge")
        finally:
            sys.modules = orig
        assert result["source"] == "hashing_tfidf"
        assert result["semantic"] is False
        assert any("优雅降级" in note for note in result["notes"])

    def test_st_preferred_absent_falls_back(self) -> None:
        monkey_none = {**sys.modules, "sentence_transformers": None}
        orig = sys.modules
        sys.modules = monkey_none  # type: ignore[assignment]
        try:
            result = resolve_embedder("sentence_transformers", model="fake/bge")
        finally:
            sys.modules = orig
        assert result["source"] == "hashing_tfidf"
        assert result["semantic"] is False
        assert any("#105" in note for note in result["notes"])

    def test_st_preferred_requires_model(self) -> None:
        with pytest.raises(ValueError, match="model"):
            resolve_embedder("sentence_transformers")

    @pytest.mark.parametrize("bad", ["bge", "", "hashing ", None, 3])
    def test_invalid_preferred_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            resolve_embedder(bad)  # type: ignore[arg-type]

    def test_st_present_swaps_in_lazy(self) -> None:
        """stub 模块在场：换装生效且模型加载惰性到首次 embed（构造零 IO）。"""
        calls: list[str] = []

        class _StubModel:
            def encode(self, texts, show_progress_bar=False):
                assert show_progress_bar is False
                calls.extend(texts)
                return [[1.0, 0.0] for _ in texts]

        class _StubModule:
            @staticmethod
            def SentenceTransformer(model_name: str) -> _StubModel:
                assert model_name == "fake/bge"
                return _StubModel()

        monkey_mod = {**sys.modules, "sentence_transformers": _StubModule}
        orig = sys.modules
        sys.modules = monkey_mod  # type: ignore[assignment]
        try:
            result = resolve_embedder("sentence_transformers", model="fake/bge")
            assert result["source"] == "sentence_transformers"
            assert result["semantic"] is True
            assert calls == []  # 构造期零加载
            vectors = result["embedder"].embed(["a", "b"])
        finally:
            sys.modules = orig
        assert vectors == [[1.0, 0.0], [1.0, 0.0]]
        assert calls == ["a", "b"]


# ---------------------------------------------------------------------------
# 召回钉 + 确定性钉
# ---------------------------------------------------------------------------

class TestSemanticRecall:
    def test_semantic_query_rank1_hit(self) -> None:
        result = semantic_query(_build_index(), "wilkinson 功分器 隔离")
        assert result["ok"] is True
        assert result["hits"], "语料内查询必须有命中"
        assert result["hits"][0]["chunk_id"] == "wk"
        assert result["mode"] == "dense_semantic"
        assert result["semantic"] is False  # 如实：降级路线非真语义

    def test_query_with_embedder_rank1_hit(self) -> None:
        result = query_with_embedder(_build_index(), "基片集成波导 金属化过孔",
                                     embedder=HashEmbedder())
        assert result["ok"] is True
        assert result["hits"][0]["chunk_id"] == "siw"

    def test_hybrid_rank1_consensus(self) -> None:
        result = hybrid_query(_build_index(), "Sobol 灵敏度 采样")
        assert result["ok"] is True
        assert result["hits"][0]["chunk_id"] == "sob"

    def test_semantic_face_version(self) -> None:
        assert SEMANTIC_FACE_VERSION == 1

    @pytest.mark.parametrize("fn", [semantic_query, hybrid_query])
    def test_determinism_byte_identical(self, fn) -> None:
        index = _build_index()
        r1 = fn(index, "KiCad 铜皮 ZONE", top_k=3)
        r2 = fn(index, "KiCad 铜皮 ZONE", top_k=3)
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_query_with_embedder_determinism(self) -> None:
        index = _build_index()
        r1 = query_with_embedder(index, "SIW 截止频率", embedder=HashEmbedder())
        r2 = query_with_embedder(index, "SIW 截止频率", embedder=HashEmbedder())
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_hit_shape_matches_bm25_contract(self) -> None:
        result = semantic_query(_build_index(), "wilkinson 隔离")
        hit = result["hits"][0]
        assert set(hit) == {"rank", "score", "chunk_id", "source_kind",
                            "citation", "snippet"}
        assert hit["citation"]["path"] == "corpus/wk.md"
        assert hit["snippet"]

    def test_empty_index_contract(self) -> None:
        for fn in (semantic_query, hybrid_query):
            result = fn(RagIndex(), "anything")
            assert result["ok"] is True
            assert result["n_indexed"] == 0
            assert result["hits"] == []
            assert result["notes"] == ["索引为空"]

    def test_empty_query_explicit_error(self) -> None:
        index = _build_index()
        for fn in (semantic_query, hybrid_query, query_with_embedder):
            result = fn(index, "。，、", embedder=HashEmbedder()) \
                if fn is query_with_embedder else fn(index, "。，、")
            assert result["ok"] is False
            assert result["errors"]
            assert result["hits"] == []

    def test_out_of_corpus_no_hit(self) -> None:
        """语料外查询：桶不相交前提下 cosine=0 → hits=[]（dim=65536 实测
        不相交前提用 hash 桶显式断言，沿 core 测试同款前提钉）。"""
        from rfauto.core.rag_embedding import hash_counts

        dim = 65536
        query = "量子隐形传态 超导磁悬浮"
        q_buckets = set(hash_counts(query, dim))
        assert q_buckets
        for _, text in _CORPUS:
            assert q_buckets.isdisjoint(hash_counts(text, dim))
        index = RagIndex()
        for cid, text in _CORPUS:
            index.add_chunk(text, {"path": f"{cid}.md"}, chunk_id=cid)
        emb = HashEmbedder(dim)
        result = query_with_embedder(index, query, embedder=emb)
        assert result["ok"] is True
        assert result["hits"] == []

    def test_duplicate_chunk_id_raises(self) -> None:
        index = RagIndex()
        index.add_chunk("text one", {"path": "a.md"}, chunk_id="same")
        index.add_chunk("text two", {"path": "b.md"}, chunk_id="same")
        with pytest.raises(ValueError, match="重复"):
            semantic_query(index, "text")


# ---------------------------------------------------------------------------
# 混合检索：alpha 端点复现单侧排序
# ---------------------------------------------------------------------------

class TestHybridEndpoints:
    def test_alpha_zero_reproduces_sparse_order(self) -> None:
        index = _build_index()
        sparse = index.query("wilkinson 功分器 SIW 波导", top_k=4)
        fused = hybrid_query(index, "wilkinson 功分器 SIW 波导", top_k=4,
                             alpha=0.0)
        sparse_ids = [h["chunk_id"] for h in sparse["hits"]]
        fused_ids = [h["chunk_id"] for h in fused["hits"]]
        assert fused_ids[:len(sparse_ids)] == sparse_ids

    def test_alpha_one_reproduces_dense_order(self) -> None:
        index = _build_index()
        dense = semantic_query(index, "wilkinson 功分器 SIW 波导", top_k=4)
        fused = hybrid_query(index, "wilkinson 功分器 SIW 波导", top_k=4,
                             alpha=1.0)
        assert [h["chunk_id"] for h in fused["hits"]] == [
            h["chunk_id"] for h in dense["hits"]]

    def test_union_and_enrichment(self) -> None:
        index = _build_index()
        fused = hybrid_query(index, "wilkinson 隔离 KiCad 铜皮", top_k=4)
        assert fused["n_union"] >= 2
        assert fused["mode"] == "hybrid_semantic"
        for hit in fused["hits"]:
            assert {"dense_score", "sparse_score", "score", "rank",
                    "chunk_id", "citation", "snippet",
                    "source_kind"} <= set(hit)

    def test_embedder_route_mode_tag(self) -> None:
        fused = hybrid_query(_build_index(), "Sobol 灵敏度",
                             embedder=HashEmbedder())
        assert fused["mode"] == "hybrid_embedder"
        assert fused["ok"] is True

    def test_empty_query_passthrough(self) -> None:
        result = hybrid_query(_build_index(), "   ")
        assert result["ok"] is False
        assert result["errors"]

    @pytest.mark.parametrize("alpha", [-0.1, 1.5, "x"])
    def test_invalid_alpha_rejected(self, alpha: object) -> None:
        with pytest.raises(ValueError):
            hybrid_query(_build_index(), "query", alpha=alpha)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 坏向量拒收钉
# ---------------------------------------------------------------------------

class _BadEmbedder:
    """按 mode 产出畸形向量的 embedder（拒收门的逐形态靶标）。"""

    def __init__(self, mode: str) -> None:
        self.mode = mode

    def embed(self, texts):
        n = len(texts)
        if self.mode == "short":
            return [[1.0, 0.0]] * max(n - 1, 1)
        if self.mode == "ragged":
            return [[1.0, 0.0]] * (n - 1) + [[1.0, 0.0, 0.0]]
        if self.mode == "nan":
            return [[float("nan"), 0.0]] * n
        if self.mode == "inf":
            return [[float("inf"), 0.0]] * n
        if self.mode == "non_numeric":
            return [["x", 0.0]] * n
        if self.mode == "bool":
            return [[True, 0.0]] * n
        if self.mode == "empty_row":
            return [[] for _ in range(n)]
        if self.mode == "non_sequence":
            return "not-a-list"
        raise AssertionError(self.mode)


class TestBadVectorRejection:
    def test_valid_vectors_pass(self) -> None:
        result = query_with_embedder(_build_index(), "wilkinson 隔离",
                                     embedder=_FakeEmbedder())
        assert result["ok"] is True

    @pytest.mark.parametrize("mode,message", [
        ("short", "期望"),
        ("ragged", "维度不一致"),
        ("nan", "非有限"),
        ("inf", "非有限"),
        ("non_numeric", "非数值"),
        ("bool", "非数值"),
        ("empty_row", "非空数值序列"),
        ("non_sequence", "向量序列"),
    ])
    def test_malformed_vectors_rejected(self, mode: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            query_with_embedder(_build_index(), "wilkinson 隔离",
                                embedder=_BadEmbedder(mode))

    def test_none_embedder_rejected(self) -> None:
        with pytest.raises(ValueError, match="embedder"):
            query_with_embedder(_build_index(), "q", embedder=None)

    def test_non_index_rejected(self) -> None:
        with pytest.raises(ValueError, match="RagIndex"):
            query_with_embedder("not-an-index", "q", embedder=_FakeEmbedder())


# ---------------------------------------------------------------------------
# 零破坏钉：既有 BM25 面与 vector_query 占位契约原样
# ---------------------------------------------------------------------------

class TestZeroBreakage:
    def test_vector_query_placeholder_contract_preserved(self) -> None:
        """既有钉（tests/unit/test_rag_service.py 同款契约，本文件独立
        复证）：配置 embedder 后 vector_query 仍显式抛 NotImplementedError
        ——语义消费走模块级新面，RagIndex 类成员零改动。"""
        index = RagIndex(embedder=_FakeEmbedder())
        with pytest.raises(NotImplementedError):
            index.vector_query("resonator")

    def test_bm25_envelope_key_set_unchanged(self) -> None:
        result = _build_index().query("wilkinson 隔离")
        assert set(result) == {"ok", "query", "query_terms", "top_k",
                               "n_indexed", "errors", "n_hits", "n_matched",
                               "hits"}

    def test_bm25_ranking_unchanged(self) -> None:
        result = _build_index().query("wilkinson 隔离")
        assert result["hits"][0]["chunk_id"] == "wk"
        assert result["n_matched"] >= 1

    def test_stats_untouched_by_semantic_face(self) -> None:
        stats = _build_index().stats()
        assert stats["embedder_configured"] is False
        assert stats["n_chunks"] == len(_CORPUS)
