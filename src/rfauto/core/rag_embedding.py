"""rag_embedding —— KD-2 RAG embedding 语义索引面（确定性降级路线，round16 规格）。

路线裁决（2026-10-02 实测，先探后做）：
- 本机 .venv **sentence-transformers / transformers 未安装**、无本地 HuggingFace
  模型缓存（~/.cache/huggingface 为空），huggingface.co 直连超时（hf-mirror
  可达，但 BGE-M3 ~2.3GB 下载 + 重型依赖安装超出本增量零网络纪律边界，且
  pyproject 的 rag extra 登记不在本增量文件面内）；
- 按 round16 KD-2 裁决条款走【确定性降级路线】：特征哈希（signed hashing
  trick）+ TF-IDF 加权的稠密向量，cosine 检索 + 与词法分数（rag_service BM25）
  的混合打分；
- 【如实声明】本模块**不是真语义 embedding，无语义泛化能力**（同义改写不
  召回——测试有边界钉），只提供确定性"词面重叠的稠密几何化"。真 embedding
  （sentence-transformers + BGE-M3）待 rag extra 落地后按 rag_service.Embedder
  协议换装：HashEmbedder.embed 与该协议同形（Sequence[str] ->
  list[list[float]]），SemanticIndex 的换装点在构造参数 embedder。

确定性：hash 用 hashlib.blake2b（**禁用内建 hash()**——str 哈希受
PYTHONHASHSEED 随机化，跨进程不确定）；分词、加权、L2 归一、打分、排序
（分数降序、同分按入库序/首见序）全为纯函数，同一输入两次查询 JSON 逐字节
一致。

分层：core 是无内部依赖叶子（.importlinter），**不 import service**——与
rag_service BM25 面的组合在消费层（tests/未来 service 薄壳）完成：
blend_rankings() 接收任意词法命中序列（含 rag_service.RagIndex.query 的
hits）。goldset 评估核 evaluate_recall 按 round16 引入的 TSA/FCA 打分模式
双口径输出（TSA=命中任一相关块、FCA=相关块全 recall）。

切块保护（KD-2"公式/代码切块保护"）：split_markdown_protected 把围栏代码块
（``` / ~~~）与数学块（$$...$$）视为原子块——永不跨块截断；超限时保持整块
并打 protected 标记（保护优先于尺寸上限，诚实 metadata 供下游识别）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

RAG_EMBEDDING_SCHEMA_VERSION = 1
DEFAULT_EMBED_DIM = 512
DEFAULT_HYBRID_ALPHA = 0.5
DEFAULT_TOP_K = 5

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE_OPEN_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_MATH_DELIM = "$$"


# ---------------------------------------------------------------------------
# 确定性分词与特征哈希
# ---------------------------------------------------------------------------

def embedding_tokenize(text: str) -> list[str]:
    """确定性分词：ASCII 词小写化 + CJK 连续段字符 bigram（单字取单字）。

    与 rag_service.tokenize 同算法（core 不 import service，本地镜像以保持
    两面词形一致；若未来 rag_service 分词演进，本函数须同步对齐并在测试钉）。
    """
    if not isinstance(text, str):
        raise ValueError("tokenize 需要 str 输入")
    tokens = _ASCII_TOKEN_RE.findall(text.lower())
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _hash_bucket(token: str, dim: int) -> tuple[int, int]:
    """blake2b 稳定哈希 -> (桶下标, 符号)。跨进程/跨解释器逐位一致。"""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
    h1 = int.from_bytes(digest[:8], "little")
    h2 = int.from_bytes(digest[8:], "little")
    return h1 % dim, (1 if h2 % 2 == 0 else -1)


def hash_counts(text: str, dim: int) -> dict[int, float]:
    """文本 -> 带符号桶计数（signed hashing trick，碰撞偏置相消）。"""
    if isinstance(dim, bool) or not isinstance(dim, int) or dim < 1:
        raise ValueError("embed_dim 必须是 >= 1 的 int")
    counts: dict[int, float] = {}
    for token in embedding_tokenize(text):
        idx, sign = _hash_bucket(token, dim)
        counts[idx] = counts.get(idx, 0.0) + float(sign)
    return counts


def _l2_normalize(vec: dict[int, float]) -> dict[int, float]:
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm <= 0.0:
        return {}
    return {k: v / norm for k, v in vec.items()}


def _dot(a: dict[int, float], b: dict[int, float]) -> float:
    if len(b) < len(a):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


# ---------------------------------------------------------------------------
# Embedder 面（与 rag_service.Embedder 协议同形；换装点）
# ---------------------------------------------------------------------------

class HashEmbedder:
    """确定性特征哈希 embedder（降级路线；非真语义 embedding）。

    embed(texts) -> list[list[float]]：与 rag_service.Embedder 协议同形，
    RagIndex(embedder=...) 可直接接收（本增量 rag_service 不调用它；真
    embedding 换装时实现同协议替换本类即可，不改调用面）。向量 = 子线性
    TF 加权 + L2 归一的带符号桶计数（无语料统计，纯逐文本确定性）。
    """

    def __init__(self, embed_dim: int = DEFAULT_EMBED_DIM) -> None:
        if isinstance(embed_dim, bool) or not isinstance(embed_dim, int) or embed_dim < 1:
            raise ValueError("embed_dim 必须是 >= 1 的 int")
        self.embed_dim = int(embed_dim)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not isinstance(texts, (tuple, list)):
            raise ValueError("texts 必须是 list/tuple[str]")
        out: list[list[float]] = []
        for text in texts:
            if not isinstance(text, str):
                raise ValueError("embed 的每个元素必须是 str")
            raw = hash_counts(text, self.embed_dim)
            weighted = {k: (1.0 + math.log(abs(v))) * (1.0 if v > 0 else -1.0)
                        for k, v in raw.items() if v != 0.0}
            normed = _l2_normalize(weighted)
            out.append([normed.get(i, 0.0) for i in range(self.embed_dim)])
        return out


# ---------------------------------------------------------------------------
# 语义（向量）索引：encode + cosine 检索（TF-IDF 桶加权）
# ---------------------------------------------------------------------------

class SemanticIndex:
    """确定性向量索引：blake2b 桶 TF-IDF 加权 + cosine 排序。

    与 RagIndex（BM25）互补：同一 citation 协议（含非空 path 的 dict）、
    同款 JSON 信封与确定性排序（分数降序、同分按入库序）。空查询/空索引/
    无命中的行为契约与 rag_service.query 一致（ok=False / ok=True hits=[]）。
    """

    def __init__(self, *, embed_dim: int = DEFAULT_EMBED_DIM) -> None:
        if isinstance(embed_dim, bool) or not isinstance(embed_dim, int) or embed_dim < 1:
            raise ValueError("embed_dim 必须是 >= 1 的 int")
        self.embed_dim = int(embed_dim)
        self._ids: list[str] = []
        self._raw: list[dict[int, float]] = []
        self._vecs: list[dict[int, float]] = []
        self._df: dict[int, int] = {}
        self._meta_extra: list[dict[str, Any]] = []

    # -- 只读视图 ---------------------------------------------------------

    @property
    def n_items(self) -> int:
        return len(self._ids)

    def stats(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schema_version": RAG_EMBEDDING_SCHEMA_VERSION,
            "embedder": "hashing_tfidf",
            "semantic": False,  # 如实：降级路线非真语义 embedding
            "embed_dim": self.embed_dim,
            "n_items": len(self._ids),
            "n_active_buckets": len(self._df),
        }

    # -- 入库 -------------------------------------------------------------

    def add(self, chunk_id: str, text: str,
            citation: dict[str, Any] | None = None,
            *, metadata: dict[str, Any] | None = None) -> None:
        """入库一条；chunk_id 必须唯一（混合打分与 goldset 评估的对齐键）。"""
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError("chunk_id 必须是非空 str")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text 必须是非空 str")
        if chunk_id in self._ids:
            raise ValueError(f"chunk_id 重复: {chunk_id}")
        if citation is not None and (
                not isinstance(citation, dict)
                or not isinstance(citation.get("path"), str)
                or not citation["path"]):
            raise ValueError("citation 必须是含非空 'path' 的 dict")
        raw = hash_counts(text, self.embed_dim)
        for bucket in raw:
            self._df[bucket] = self._df.get(bucket, 0) + 1
        self._ids.append(chunk_id)
        self._raw.append(raw)
        self._vecs.append({})  # 惰性：首次查询时统一加权
        self._meta_extra.append({
            "citation": dict(citation) if citation else {},
            "metadata": dict(metadata or {}),
        })

    def _finalize_vectors(self) -> None:
        n_docs = len(self._ids)
        for i, raw in enumerate(self._raw):
            if self._vecs[i]:
                continue
            weighted: dict[int, float] = {}
            for bucket, count in raw.items():
                df = self._df.get(bucket, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                if count == 0.0:
                    continue
                weighted[bucket] = (1.0 + math.log(abs(count))) * (
                    1.0 if count > 0 else -1.0) * idf
            self._vecs[i] = _l2_normalize(weighted)

    def _query_vector(self, text: str) -> dict[int, float]:
        n_docs = max(len(self._ids), 1)
        raw = hash_counts(text, self.embed_dim)
        weighted: dict[int, float] = {}
        for bucket, count in raw.items():
            if count == 0.0:
                continue
            df = self._df.get(bucket, 0)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            weighted[bucket] = (1.0 + math.log(abs(count))) * (
                1.0 if count > 0 else -1.0) * idf
        return _l2_normalize(weighted)

    # -- 检索 -------------------------------------------------------------

    def query(self, text: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """cosine 检索入口：返回 {ok, hits, ...} JSON 契约。

        - 空/纯空白查询：ok=False + errors（与 rag_service.query 同契约）；
        - 空索引：ok=True、n_indexed=0、hits=[]；
        - 语料外查询（所有桶 cosine=0）：ok=True、hits=[]（确定性无命中）；
        - 非法输入（非 str / top_k < 1）：ValueError。
        """
        if not isinstance(text, str):
            raise ValueError("query text 必须是 str")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k 必须是 >= 1 的 int")
        base: dict[str, Any] = {
            "query": text,
            "top_k": top_k,
            "n_indexed": len(self._ids),
        }
        if not embedding_tokenize(text):
            return {**base, "ok": False,
                    "errors": ["query 为空或仅含空白/标点字符"],
                    "n_hits": 0, "hits": []}
        if not self._ids:
            return {**base, "ok": True, "errors": [], "n_hits": 0,
                    "hits": [], "notes": ["索引为空"]}
        self._finalize_vectors()
        qvec = self._query_vector(text)
        scored: list[tuple[float, int]] = []
        for i, dvec in enumerate(self._vecs):
            score = _dot(qvec, dvec)
            if score > 1e-12:
                scored.append((score, i))
        # 分数降序、同分按入库序（确定性）
        scored.sort(key=lambda item: (-item[0], item[1]))
        hits: list[dict[str, Any]] = []
        for rank, (score, idx) in enumerate(scored[:top_k], start=1):
            extra = self._meta_extra[idx]
            hits.append({
                "rank": rank,
                "score": score,
                "chunk_id": self._ids[idx],
                "citation": dict(extra["citation"]),
                "metadata": dict(extra["metadata"]),
            })
        return {**base, "ok": True, "errors": [], "n_hits": len(hits),
                "hits": hits}

    def dumps(self) -> str:
        """canonical JSON 快照（确定性逐字节比对用）。"""
        return json.dumps(self.stats(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))


# ---------------------------------------------------------------------------
# 混合打分：dense（本模块）× sparse（rag_service BM25 面在消费层传入）
# ---------------------------------------------------------------------------

def _normalize_scores(pairs: list[tuple[int, str, float]]) -> dict[str, float]:
    """max 归一到 [0,1]；全零/空侧安全（全 0）。保序输入附 first-seen 序。"""
    peak = max((s for _, _, s in pairs), default=0.0)
    if peak <= 0.0:
        return {cid: 0.0 for _, cid, _ in pairs}
    return {cid: s / peak for _, cid, s in pairs}


def blend_rankings(
    dense: Sequence[Mapping[str, Any]],
    sparse: Sequence[Mapping[str, Any]],
    *,
    alpha: float = DEFAULT_HYBRID_ALPHA,
    top_k: int | None = None,
) -> dict[str, Any]:
    """混合打分核：fused = alpha·dense_norm + (1-alpha)·sparse_norm。

    dense/sparse 是 [{"chunk_id", "score"}, ...] 形态的命中序列（sparse 侧
    在消费层直接传 rag_service RagIndex.query 的 hits——core 不 import
    service）。两侧各自 max 归一后线性融合；只出现一侧的 chunk_id 另一侧
    记 0.0。排序：fused 降序、同分按 dense 侧首见序、再按 sparse 侧首见序、
    再按 chunk_id 字典序（全确定性，无随机兜底）。
    """
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError("alpha 必须是 [0, 1] 内的数")
    alpha_f = float(alpha)
    if not 0.0 <= alpha_f <= 1.0:
        raise ValueError("alpha 必须是 [0, 1] 内的数")
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int)
                              or top_k < 1):
        raise ValueError("top_k 必须是 >= 1 的 int 或 None")

    def _side(items: Sequence[Mapping[str, Any]], name: str
              ) -> tuple[dict[str, float], dict[str, int]]:
        scores: dict[str, float] = {}
        order: dict[str, int] = {}
        for pos, item in enumerate(items):
            if not isinstance(item, Mapping) or "chunk_id" not in item or "score" not in item:
                raise ValueError(f"{name} 命中必须是含 chunk_id/score 的映射")
            cid = item["chunk_id"]
            score = item["score"]
            if not isinstance(cid, str) or not cid:
                raise ValueError(f"{name} chunk_id 必须是非空 str")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError(f"{name} score 必须是数值")
            if score < 0:
                raise ValueError(f"{name} score 必须非负（词法/cosine 分数量域）")
            if cid not in scores:
                scores[cid] = float(score)
                order[cid] = pos
        return scores, order

    dense_scores, dense_order = _side(dense, "dense")
    sparse_scores, sparse_order = _side(sparse, "sparse")
    dense_norm = _normalize_scores(
        [(dense_order[cid], cid, s) for cid, s in dense_scores.items()])
    sparse_norm = _normalize_scores(
        [(sparse_order[cid], cid, s) for cid, s in sparse_scores.items()])

    union: list[str] = []
    seen: set[str] = set()
    for cid in list(dense_scores) + list(sparse_scores):
        if cid not in seen:
            seen.add(cid)
            union.append(cid)
    rows: list[dict[str, Any]] = []
    for cid in union:
        d = dense_norm.get(cid, 0.0)
        s = sparse_norm.get(cid, 0.0)
        rows.append({
            "chunk_id": cid,
            "dense_score": dense_scores.get(cid, 0.0),
            "sparse_score": sparse_scores.get(cid, 0.0),
            "dense_norm": d,
            "sparse_norm": s,
            "score": alpha_f * d + (1.0 - alpha_f) * s,
        })
    rows.sort(key=lambda r: (-r["score"],
                             dense_order.get(r["chunk_id"], len(union)),
                             sparse_order.get(r["chunk_id"], len(union)),
                             r["chunk_id"]))
    limit = len(rows) if top_k is None else min(top_k, len(rows))
    for rank, row in enumerate(rows[:limit], start=1):
        row["rank"] = rank
    return {
        "ok": True,
        "alpha": alpha_f,
        "n_dense": len(dense_scores),
        "n_sparse": len(sparse_scores),
        "n_union": len(union),
        "hits": rows[:limit],
    }


# ---------------------------------------------------------------------------
# goldset 评估核（TSA/FCA 双口径，round16 KD-2"评估集"）
# ---------------------------------------------------------------------------

def evaluate_recall(
    index: SemanticIndex,
    goldset: Sequence[Mapping[str, Any]],
    *,
    k: int = 5,
) -> dict[str, Any]:
    """gold 问题集 recall@k 评估（JSON 契约，确定性）。

    goldset 条目：{"query": str, "relevant": [chunk_id, ...]}。打分模式沿
    round16 引入的 TSA/FCA 口径：
    - TSA（选对）：top-k 命中任一相关块即计 1——tsa@k = 命中率；
    - FCA（关键全对）：top-k 覆盖全部相关块才计 1——fca@k = 全召回率；
    另报逐项 recall@k 均值（|∩|/|relevant| 宏平均）。
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k 必须是 >= 1 的 int")
    rows: list[dict[str, Any]] = []
    for item in goldset:
        if not isinstance(item, Mapping) or "query" not in item or "relevant" not in item:
            raise ValueError("goldset 条目必须含 query/relevant")
        query = item["query"]
        relevant = item["relevant"]
        if not isinstance(query, str):
            raise ValueError("goldset query 必须是 str")
        if (not isinstance(relevant, (list, tuple))
                or not all(isinstance(c, str) for c in relevant)):
            raise ValueError("goldset relevant 必须是 list[str]")
        result = index.query(query, top_k=k)
        got = [hit["chunk_id"] for hit in result["hits"]]
        rel = list(dict.fromkeys(relevant))
        inter = [c for c in got if c in rel]
        rows.append({
            "query": query,
            "relevant": rel,
            "retrieved": got,
            "n_relevant": len(rel),
            "n_hit": len(inter),
            "tsa": 1 if inter else 0,
            "fca": 1 if rel and set(rel).issubset(got) else 0,
            "recall": (len(inter) / len(rel)) if rel else 0.0,
        })
    n = len(rows)
    return {
        "ok": True,
        "k": k,
        "n_queries": n,
        "tsa_at_k": (sum(r["tsa"] for r in rows) / n) if n else 0.0,
        "fca_at_k": (sum(r["fca"] for r in rows) / n) if n else 0.0,
        "mean_recall_at_k": (sum(r["recall"] for r in rows) / n) if n else 0.0,
        "items": rows,
    }


# ---------------------------------------------------------------------------
# 公式/代码切块保护（KD-2"公式/代码切块保护"）
# ---------------------------------------------------------------------------

def split_markdown_protected(
    text: str,
    *,
    max_chars: int = 800,
) -> list[dict[str, Any]]:
    """带公式/代码原子保护的 Markdown 切块。

    - 围栏代码块（``` 或 ~~~）与数学块（$$...$$ 独立行开启）是**原子块**：
      永不跨块截断；超过 max_chars 时保持整块独占并打
      metadata["protected"]=True（保护优先于尺寸上限——截断的公式/代码对
      检索与引用都是坏块，诚实超标优于静默切碎）；
    - 其余文本按标题切段、段落续切（与 rag_service.split_markdown 同策略的
      core 侧镜像），返回 [{"heading", "line", "text", "protected", "kind"}]；
    - 行号 = 块起始行（1 基）；未闭合围栏把剩余全文作为一个受保护块（诚实
      处理畸形输入，不静默吞）。
    """
    if not isinstance(text, str):
        raise ValueError("split_markdown_protected 需要 str 输入")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars 必须是 >= 1 的 int")
    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    heading = ""
    prose: list[str] = []
    prose_start = 1

    def _flush_prose() -> None:
        nonlocal prose
        body = "\n".join(prose).strip("\n")
        prose = []
        if not body.strip():
            return
        content = (heading + "\n" + body) if heading else body
        for piece in _split_plain(content, max_chars):
            chunks.append({"heading": heading, "line": prose_start,
                           "text": piece, "protected": False, "kind": "prose"})

    def _consume_protected(kind: str, close_pred) -> None:
        """从当前行起消费一个原子块（含开/闭界标）到 chunks。"""
        nonlocal i, lineno
        block = [lines[i]]
        start_line = lineno
        i += 1
        lineno += 1
        while i < len(lines):
            block.append(lines[i])
            if close_pred(lines[i].strip()):
                i += 1
                lineno += 1
                break
            i += 1
            lineno += 1
        chunks.append({
            "heading": heading,
            "line": start_line,
            "text": "\n".join(block).strip("\n"),
            "protected": True,
            "kind": kind,
        })

    i = 0
    lineno = 1
    while i < len(lines):
        line = lines[i]
        fence_match = _FENCE_OPEN_RE.match(line)
        if fence_match is not None:
            _flush_prose()
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            _consume_protected(
                "code",
                lambda s, c=fence_char, n=fence_len: s.startswith(c * n)
                and set(s) <= {c})
            continue
        if line.strip() == _MATH_DELIM:
            _flush_prose()
            _consume_protected("math", lambda s: s == _MATH_DELIM)
            continue
        head_match = _HEADING_RE.match(line)
        if head_match is not None:
            _flush_prose()
            heading = head_match.group(2).strip()
            prose_start = lineno
            i += 1
            lineno += 1
            continue
        if not prose:
            prose_start = lineno
        prose.append(line)
        i += 1
        lineno += 1
    _flush_prose()
    return chunks


def _split_plain(text: str, max_chars: int) -> list[str]:
    """按段落优先、超长段落硬切的顺序拆 <= max_chars 的块（core 侧镜像）。"""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if len(para) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(para[i:i + max_chars]
                          for i in range(0, len(para), max_chars))
            continue
        candidate = para if not current else current + "\n\n" + para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = para
    if current:
        pieces.append(current)
    return pieces
