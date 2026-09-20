"""rag_service —— F2 RAG 知识库（确定性词法检索版，方案 F2）。

面向"引用可溯"的本地知识检索服务：索引两类来源并返回带 citation 的命中。

1. 仓库文档（docs/**/*.md）：按标题/段落切块，citation = 相对路径 + 标题 +
  起始行号；
2. runs/ 战役元数据（<run>/meta.json 与 <run>/recipe.snapshot.yaml）：按
  模板(model)/adapter/study/参数/结论(status)建可检索条目，
  citation = run 目录相对路径 + 字段文件。

检索内核是自研 BM25（纯 stdlib，确定性、无网络、无 embedding 模型、无向量
库）；query 返回命中列表（score + citation + 摘录），explain 额外给出逐词
分数明细（tf/df/idf/contribution）供可溯。

与 E1 结构化查询（dataset_service，runs 点级数据 SQL）互补：本模块只读文档
与元数据做词法全文检索，不修改 E1 任何接口，也不与其共享状态。

embedding 在本增量未实现：仅预留 Embedder 协议与 RagIndex(embedder=...) 形参，
调用 RagIndex.vector_query 显式抛 NotImplementedError——绝不伪造向量结果
（军规 7：数值只在确定性内核）。

确定性：分词、切块、BM25 打分、摘录窗口与排序（分数降序、同分按入库序）全部
为纯函数；同一输入同一索引两次查询逐字节一致（dumps / json.dumps）。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

RAG_SCHEMA_VERSION = 1
BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_TOP_K = 5
DEFAULT_MAX_CHUNK_CHARS = 800
DEFAULT_SNIPPET_CHARS = 160

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# meta.json 里参与词法条目的关键字段（模板/adapter/study/结论）
_RUN_META_FIELDS = (
  "run_id",
  "model",
  "adapter",
  "status",
  "study_name",
  "seed",
  "timestamp",
  "schema_version",
)


class Embedder(Protocol):
  """可插拔向量化后端协议（本增量只留接口，不实现）。

  实现方需返回与入参等长的稠密向量列表。rag_service 本增量不会调用它；
  向量检索走 RagIndex.vector_query 时显式抛 NotImplementedError。保留协议
  与形参是为了后续增量替换内核时不改动调用面。
  """

  def embed(self, texts: Sequence[str]) -> list[list[float]]:
    ... # pragma: no cover - 协议声明


@dataclass
class Chunk:
  """一个可检索块：正文 + 可溯 citation。"""

  chunk_id: str
  text: str
  citation: dict[str, Any]
  source_kind: str = "doc"
  metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 确定性分词与切块
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
  """确定性分词：ASCII 词小写化 + CJK 连续段取字符 bigram（单字取单字）。

  不引入分词库/embedding。ASCII 词按出现顺序在前，CJK 词元随后追加——BM25
  是词袋模型，顺序不影响打分；同一输入永远给出同一词序列。
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


def _split_long(text: str, max_chars: int) -> list[str]:
  """按段落优先、超长段落硬切的顺序，把 text 拆成 <= max_chars 的块。"""
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


def split_markdown(text: str, *, max_chars: int = DEFAULT_MAX_CHUNK_CHARS
          ) -> list[dict[str, Any]]:
  """把 Markdown 按标题切段、按段落续切。

  返回 [{"heading", "line", "text"}, ...]：line 是该段标题所在行号（无标题
  前导段为 1）；标题文本会并入块正文，保证按标题词也能命中。
  """
  if not isinstance(text, str):
    raise ValueError("split_markdown 需要 str 输入")
  if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
    raise ValueError("max_chars 必须是 >= 1 的 int")
  lines = text.splitlines()
  sections: list[tuple[str, int, list[str]]] = []
  heading = ""
  start = 1
  body: list[str] = []
  for lineno, line in enumerate(lines, start=1):
    match = _HEADING_RE.match(line)
    if match:
      if body:
        sections.append((heading, start, body))
      heading = match.group(2).strip()
      start = lineno
      body = []
    else:
      body.append(line)
  if body:
    sections.append((heading, start, body))
  if not sections and text.strip():
    sections.append(("", 1, lines))

  chunks: list[dict[str, Any]] = []
  for sec_heading, sec_start, sec_body in sections:
    body_text = "\n".join(sec_body).strip("\n")
    if sec_heading and body_text:
      content = sec_heading + "\n" + body_text
    elif sec_heading:
      content = sec_heading
    else:
      content = body_text
    if not content.strip():
      continue
    for piece in _split_long(content, max_chars):
      chunks.append({"heading": sec_heading, "line": sec_start,
              "text": piece})
  return chunks


# ---------------------------------------------------------------------------
# runs/ 条目文本
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any] | None:
  try:
    data = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError, UnicodeDecodeError):
    return None
  return data if isinstance(data, dict) else None


def _run_meta_text(run_id: str, data: dict[str, Any]) -> str:
  """把 meta.json 关键字段拼成确定性条目文本。"""
  lines = [f"run {run_id}"]
  for key in _RUN_META_FIELDS:
    value = data.get(key)
    if value is not None:
      lines.append(f"{key}: {value}")
  metrics = data.get("metrics")
  if isinstance(metrics, dict):
    for key in sorted(metrics, key=str):
      value = metrics[key]
      if isinstance(value, bool) or not isinstance(value, (int, float)):
        continue
      lines.append(f"metric {key}: {value}")
  return "\n".join(lines)


def _recipe_entry_text(raw: str) -> str:
  """recipe.snapshot.yaml → 确定性参数/目标条目文本。

  best-effort：PyYAML 缺失或解析失败时退回原文（仍可词法检索），不让观测性
  步骤成为故障点（#105）。
  """
  data: Any = None
  try:
    import yaml

    data = yaml.safe_load(raw)
  except Exception:
    data = None
  if not isinstance(data, dict):
    return raw
  lines: list[str] = []
  model = data.get("model")
  if model is not None:
    lines.append(f"model: {model}")
  params = data.get("params")
  if isinstance(params, dict):
    for key in sorted(params, key=str):
      value = params[key]
      if isinstance(value, dict):
        lines.append(
          f"param {key}: value={value.get('value')} "
          f"unit={value.get('unit', '')}")
      else:
        lines.append(f"param {key}: {value}")
  optimization = data.get("optimization")
  if isinstance(optimization, dict) and isinstance(optimization.get("params"), dict):
    for key in sorted(optimization["params"], key=str):
      bounds = optimization["params"][key]
      if isinstance(bounds, dict):
        lines.append(
          f"opt-param {key}: low={bounds.get('low')} "
          f"high={bounds.get('high')}")
  objectives = data.get("objectives")
  if isinstance(objectives, list):
    for idx, objective in enumerate(objectives):
      if isinstance(objective, dict):
        lines.append(
          f"objective {idx}: metric={objective.get('metric')} "
          f"op={objective.get('op')} band={objective.get('band')} "
          f"value={objective.get('value')}")
  return "\n".join(lines) if lines else raw


# ---------------------------------------------------------------------------
# 摘录与排序辅助
# ---------------------------------------------------------------------------

def _snippet(text: str, terms: Sequence[str],
       width: int = DEFAULT_SNIPPET_CHARS) -> str:
  """以首个命中词为中心截取确定性摘录（无命中则取头部）。"""
  if not text:
    return ""
  if isinstance(width, bool) or not isinstance(width, int) or width < 1:
    raise ValueError("snippet width 必须是 >= 1 的 int")
  low = text.lower()
  pos = -1
  for term in terms:
    found = low.find(term)
    if found != -1 and (pos == -1 or found < pos):
      pos = found
  if pos == -1:
    window = text[:width]
    return window + ("…" if len(text) > width else "")
  start = max(0, pos - width // 3)
  end = min(len(text), start + width)
  start = max(0, end - width)
  body = text[start:end].replace("\n", " ").strip()
  prefix = "…" if start > 0 else ""
  suffix = "…" if end < len(text) else ""
  return prefix + body + suffix


def _unique_terms(tokens: Sequence[str]) -> list[str]:
  """按首次出现顺序去重（BM25 对每个查询词只计一次）。"""
  seen: set[str] = set()
  out: list[str] = []
  for token in tokens:
    if token not in seen:
      seen.add(token)
      out.append(token)
  return out


def _validate_query(text: str, top_k: int) -> tuple[list[str], int]:
  if not isinstance(text, str):
    raise ValueError("query text 必须是 str")
  if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
    raise ValueError("top_k 必须是 >= 1 的 int")
  return _unique_terms(tokenize(text)), top_k


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------

class RagIndex:
  """确定性词法 BM25 索引；citation 可溯（文件 + 标题/行号/字段）。"""

  def __init__(
    self,
    *,
    base_dir: str | Path | None = None,
    embedder: Embedder | None = None,
    k1: float = BM25_K1,
    b: float = BM25_B,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
  ) -> None:
    if float(k1) < 0.0:
      raise ValueError("BM25 k1 必须 >= 0")
    if not 0.0 <= float(b) <= 1.0:
      raise ValueError("BM25 b 必须位于 [0, 1]")
    self.base_dir = Path(base_dir).resolve() if base_dir is not None else None
    self.embedder = embedder
    self.k1 = float(k1)
    self.b = float(b)
    self.max_chunk_chars = int(max_chunk_chars)
    self._chunks: list[Chunk] = []
    self._tf: list[dict[str, int]] = []
    self._doc_len: list[int] = []
    self._df: dict[str, int] = {}
    self._avgdl = 0.0

  # -- 只读视图 ---------------------------------------------------------

  @property
  def n_chunks(self) -> int:
    return len(self._chunks)

  @property
  def chunks(self) -> tuple[Chunk, ...]:
    return tuple(self._chunks)

  def stats(self) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    for chunk in self._chunks:
      kinds[chunk.source_kind] = kinds.get(chunk.source_kind, 0) + 1
    return {
      "ok": True,
      "schema_version": RAG_SCHEMA_VERSION,
      "n_chunks": len(self._chunks),
      "vocab_size": len(self._df),
      "avgdl": self._avgdl,
      "source_kinds": kinds,
      "embedder_configured": self.embedder is not None,
    }

  # -- 入库 -------------------------------------------------------------

  def add_chunk(
    self,
    text: str,
    citation: dict[str, Any],
    *,
    source_kind: str = "doc",
    metadata: dict[str, Any] | None = None,
    chunk_id: str | None = None,
  ) -> str:
    """加入一个可检索块；citation 必须含非空 path。"""
    if not isinstance(text, str) or not text.strip():
      raise ValueError("chunk text 必须是非空 str")
    if (not isinstance(citation, dict)
        or not isinstance(citation.get("path"), str)
        or not citation["path"]):
      raise ValueError("citation 必须是含非空 'path' 的 dict")
    cid = chunk_id or f"c{len(self._chunks):06d}"
    tokens = tokenize(text)
    tf: dict[str, int] = {}
    for token in tokens:
      tf[token] = tf.get(token, 0) + 1
    self._chunks.append(Chunk(
      chunk_id=cid,
      text=text,
      citation=dict(citation),
      source_kind=source_kind,
      metadata=dict(metadata or {}),
    ))
    self._tf.append(tf)
    self._doc_len.append(len(tokens))
    for token in tf:
      self._df[token] = self._df.get(token, 0) + 1
    self._avgdl = sum(self._doc_len) / len(self._doc_len)
    return cid

  def _rel(self, path: Path) -> str:
    resolved = Path(path).resolve()
    if self.base_dir is None:
      return resolved.as_posix()
    try:
      return resolved.relative_to(self.base_dir).as_posix()
    except ValueError:
      return resolved.as_posix()

  def resolve(self, citation: dict[str, Any]) -> Path:
    """把 citation 还原为可校验的文件路径（citation 可溯的机器入口）。"""
    if not isinstance(citation, dict) or not isinstance(citation.get("path"), str):
      raise ValueError("citation 必须是含 'path' 的 dict")
    path = Path(citation["path"])
    if not path.is_absolute() and self.base_dir is not None:
      return self.base_dir / path
    return path

  def add_document(self, path: str | Path, *, rel_path: str | None = None,
           max_chars: int | None = None) -> list[str]:
    """读一个 Markdown 文件并按标题/段落切块入库，返回块 id 列表。"""
    doc = Path(path)
    if not doc.is_file():
      raise FileNotFoundError(f"文档不存在: {doc}")
    text = doc.read_text(encoding="utf-8")
    rel = rel_path or self._rel(doc)
    mcc = self.max_chunk_chars if max_chars is None else max_chars
    ids: list[str] = []
    for part in split_markdown(text, max_chars=mcc):
      citation = {
        "kind": "doc",
        "path": rel,
        "heading": part["heading"],
        "line": part["line"],
      }
      ids.append(self.add_chunk(
        part["text"], citation, source_kind="doc",
        metadata={"heading": part["heading"], "line": part["line"]}))
    return ids

  def index_documents(self, docs_dir: str | Path, *,
            pattern: str = "*.md") -> int:
    """递归索引目录下匹配 pattern 的文档，返回新增块数（路径排序确定）。"""
    directory = Path(docs_dir)
    if not directory.is_dir():
      raise FileNotFoundError(f"docs 目录不存在: {directory}")
    files = sorted((p for p in directory.rglob(pattern) if p.is_file()),
            key=lambda p: p.as_posix())
    count = 0
    for file in files:
      count += len(self.add_document(file))
    return count

  def index_runs(self, runs_dir: str | Path, *, limit: int | None = None) -> int:
    """索引 runs/ 下每个 run 的 meta.json 与 recipe.snapshot.yaml。

    返回新增块数；run 目录按名字排序。畸形 meta.json / 缺失文件跳过
    （best-effort，#105），不阻塞整体索引。
    """
    root = Path(runs_dir)
    if not root.is_dir():
      raise FileNotFoundError(f"runs 目录不存在: {root}")
    if limit is not None and (isinstance(limit, bool)
                 or not isinstance(limit, int) or limit < 0):
      raise ValueError("limit 必须是非负 int")
    run_dirs = sorted((p for p in root.iterdir() if p.is_dir()),
             key=lambda p: p.name)
    if limit is not None:
      run_dirs = run_dirs[:limit]
    count = 0
    for run_dir in run_dirs:
      meta = run_dir / "meta.json"
      if meta.is_file():
        data = _read_json(meta)
        if data is not None:
          citation = {"kind": "run", "path": self._rel(meta),
                "run_id": run_dir.name, "field": "meta.json"}
          self.add_chunk(
            _run_meta_text(run_dir.name, data), citation,
            source_kind="run",
            metadata={"run_id": run_dir.name, "file": "meta.json"})
          count += 1
      recipe = run_dir / "recipe.snapshot.yaml"
      if recipe.is_file():
        try:
          raw = recipe.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
          raw = ""
        if raw.strip():
          citation = {
            "kind": "run", "path": self._rel(recipe),
            "run_id": run_dir.name,
            "field": "recipe.snapshot.yaml",
          }
          self.add_chunk(
            _recipe_entry_text(raw), citation, source_kind="run",
            metadata={"run_id": run_dir.name,
                 "file": "recipe.snapshot.yaml"})
          count += 1
    return count

  # -- 检索 -------------------------------------------------------------

  def _idf(self, term: str) -> float:
    df = self._df.get(term, 0)
    return math.log(1.0 + (len(self._chunks) - df + 0.5) / (df + 0.5))

  def _rank(self, query_terms: Sequence[str]) -> list[dict[str, Any]]:
    idf_cache = {term: self._idf(term) for term in query_terms}
    results: list[dict[str, Any]] = []
    for idx, tf in enumerate(self._tf):
      doc_len = self._doc_len[idx]
      norm = 1.0 - self.b + self.b * (
        doc_len / self._avgdl if self._avgdl > 0.0 else 0.0)
      score = 0.0
      breakdown: list[dict[str, Any]] = []
      for term in query_terms:
        freq = tf.get(term, 0)
        if freq == 0:
          continue
        idf = idf_cache[term]
        contribution = idf * (freq * (self.k1 + 1.0)) / (
          freq + self.k1 * norm)
        score += contribution
        breakdown.append({
          "term": term,
          "tf": freq,
          "df": self._df.get(term, 0),
          "idf": idf,
          "contribution": contribution,
        })
      if score > 0.0:
        results.append({"index": idx, "score": score,
                "breakdown": breakdown})
    # 分数降序、同分按入库序（确定性）
    results.sort(key=lambda item: (-item["score"], item["index"]))
    return results

  def _hit(self, ranked: dict[str, Any], rank: int,
       query_terms: Sequence[str], *,
       with_breakdown: bool = False) -> dict[str, Any]:
    chunk = self._chunks[ranked["index"]]
    hit: dict[str, Any] = {
      "rank": rank,
      "score": ranked["score"],
      "chunk_id": chunk.chunk_id,
      "source_kind": chunk.source_kind,
      "citation": dict(chunk.citation),
      "snippet": _snippet(chunk.text, query_terms),
    }
    if with_breakdown:
      hit["score_breakdown"] = ranked["breakdown"]
    return hit

  def query(self, text: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """词法检索入口：返回 {ok, hits, ...} JSON 契约。

    - 空/纯空白查询：ok=False + errors（显式行为，不抛异常）；
    - 空索引：ok=True、n_indexed=0、hits=[]；
    - 无命中（未知词）：ok=True、hits=[]；
    - 非法输入（非 str / top_k < 1）：ValueError。
    """
    query_terms, k = _validate_query(text, top_k)
    base: dict[str, Any] = {
      "query": text,
      "query_terms": query_terms,
      "top_k": k,
      "n_indexed": len(self._chunks),
    }
    if not query_terms:
      return {**base, "ok": False, "errors": ["query 为空或仅含空白/标点字符"],
          "n_hits": 0, "n_matched": 0, "hits": []}
    if not self._chunks:
      return {**base, "ok": True, "errors": [], "n_hits": 0,
          "n_matched": 0, "hits": [], "notes": ["索引为空"]}
    ranked = self._rank(query_terms)
    hits = [self._hit(item, rank, query_terms)
        for rank, item in enumerate(ranked[:k], start=1)]
    return {**base, "ok": True, "errors": [], "n_hits": len(hits),
        "n_matched": len(ranked), "hits": hits}

  def explain(self, text: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """同 query，但每个命中附逐词分数明细（可溯 BM25 打分）。"""
    result = self.query(text, top_k)
    if not result["ok"] or not result["hits"]:
      return result
    query_terms = result["query_terms"]
    ranked = self._rank(query_terms)
    result["hits"] = [
      self._hit(item, rank, query_terms, with_breakdown=True)
      for rank, item in enumerate(ranked[:result["top_k"]], start=1)
    ]
    return result

  def vector_query(self, text: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """向量检索占位：本增量未实现（不伪造 embedding 结果）。"""
    raise NotImplementedError(
      "向量检索未实现：本增量只提供确定性词法 BM25（无 embedding 模型/"
      "向量库）；Embedder 协议已预留，待后续增量接入。")

  # -- 确定性导出 -------------------------------------------------------

  def to_dict(self) -> dict[str, Any]:
    """JSON 可序列化快照（用于逐字节确定性比对/持久化）。"""
    return {
      "schema_version": RAG_SCHEMA_VERSION,
      "k1": self.k1,
      "b": self.b,
      "n_chunks": len(self._chunks),
      "chunks": [
        {
          "chunk_id": chunk.chunk_id,
          "text": chunk.text,
          "citation": dict(chunk.citation),
          "source_kind": chunk.source_kind,
          "metadata": dict(chunk.metadata),
        }
        for chunk in self._chunks
      ],
      "df": dict(sorted(self._df.items())),
    }

  def dumps(self) -> str:
    """canonical JSON 串（ensure_ascii=False + sort_keys + 紧凑分隔符）。"""
    return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
             separators=(",", ":"))


# ---------------------------------------------------------------------------
# 服务层便利函数（JSON 进出）
# ---------------------------------------------------------------------------

def build_index(
  *,
  docs_dir: str | Path | None = None,
  runs_dir: str | Path | None = None,
  base_dir: str | Path | None = None,
  embedder: Embedder | None = None,
  runs_limit: int | None = None,
) -> RagIndex:
  """构建索引：可选索引文档目录与 runs 目录，返回 RagIndex。"""
  index = RagIndex(base_dir=base_dir, embedder=embedder)
  if docs_dir is not None:
    index.index_documents(docs_dir)
  if runs_dir is not None:
    index.index_runs(runs_dir, limit=runs_limit)
  return index


def query(index: RagIndex, text: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
  """服务层检索函数：query(index, text, top_k) -> {ok, hits, ...}。"""
  if not isinstance(index, RagIndex):
    raise ValueError("index 必须是 RagIndex 实例")
  return index.query(text, top_k)


def explain(index: RagIndex, text: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
  """服务层解释函数：命中带逐词 BM25 分数明细。"""
  if not isinstance(index, RagIndex):
    raise ValueError("index 必须是 RagIndex 实例")
  return index.explain(text, top_k)


# ---------------------------------------------------------------------------
# 一步式语料包装（CLI/MCP 薄壳消费；JSON 信封，不改内核逻辑）
# ---------------------------------------------------------------------------

def _safe_build_corpus_index(
  *,
  docs_dir: str | Path | None,
  runs_dir: str | Path | None,
  base_dir: str | Path | None,
  runs_limit: int | None,
) -> tuple[RagIndex | None, list[str] | None]:
  """build_index 的信封化变体：目录缺失返回 (None, errors) 而非抛异常。

  壳层（CLI/MCP）零逻辑约定：服务层永远 JSON 进出，ok=False 显式报错。
  """
  try:
    index = build_index(docs_dir=docs_dir, runs_dir=runs_dir,
              base_dir=base_dir, runs_limit=runs_limit)
  except FileNotFoundError as exc:
    return None, [f"索引构建失败: {exc}"]
  return index, None


def index_corpus(
  *,
  docs_dir: str | Path | None = None,
  runs_dir: str | Path | None = None,
  base_dir: str | Path | None = None,
  runs_limit: int | None = None,
) -> dict[str, Any]:
  """构建索引并返回统计快照（n_chunks/vocab/source_kinds，JSON 信封）。"""
  index, errors = _safe_build_corpus_index(
    docs_dir=docs_dir, runs_dir=runs_dir, base_dir=base_dir,
    runs_limit=runs_limit)
  if index is None:
    return {"ok": False, "errors": errors or ["索引构建失败"]}
  return index.stats()


def query_corpus(
  text: str,
  *,
  top_k: int = DEFAULT_TOP_K,
  docs_dir: str | Path | None = None,
  runs_dir: str | Path | None = None,
  base_dir: str | Path | None = None,
  runs_limit: int | None = None,
) -> dict[str, Any]:
  """构建索引并词法检索（一步式；命中含 score + citation + snippet）。"""
  index, errors = _safe_build_corpus_index(
    docs_dir=docs_dir, runs_dir=runs_dir, base_dir=base_dir,
    runs_limit=runs_limit)
  if index is None:
    return {"ok": False, "errors": errors or ["索引构建失败"]}
  return query(index, text, top_k)


def explain_corpus(
  text: str,
  *,
  top_k: int = DEFAULT_TOP_K,
  docs_dir: str | Path | None = None,
  runs_dir: str | Path | None = None,
  base_dir: str | Path | None = None,
  runs_limit: int | None = None,
) -> dict[str, Any]:
  """同 query_corpus，但每个命中附逐词 BM25 分数明细（打分可溯）。"""
  index, errors = _safe_build_corpus_index(
    docs_dir=docs_dir, runs_dir=runs_dir, base_dir=base_dir,
    runs_limit=runs_limit)
  if index is None:
    return {"ok": False, "errors": errors or ["索引构建失败"]}
  return explain(index, text, top_k)
